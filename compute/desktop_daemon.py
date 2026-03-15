#!/usr/bin/env python3
"""
Way2AGI Desktop Compute Manager Daemon
=======================================
Verwaltet GPU-Ressourcen (RTX 5090, 32GB VRAM) fuer Way2AGI.
Laeuft als standalone Daemon auf dem Desktop PC.

Dependencies:
    pip install fastapi uvicorn httpx psutil pynvml

Starten:
    python3 desktop_daemon.py

Konfiguration ueber Umgebungsvariablen:
    OLLAMA_URL          (default: http://YOUR_COMPUTE_NODE_IP:11434)
    DAEMON_PORT         (default: 8100)
    CONTROLLER_URL      (default: http://YOUR_COMPUTE_NODE_IP:8050)
    HEARTBEAT_INTERVAL  (default: 60)
    IDLE_TIMEOUT        (default: 1800)
"""

import asyncio
import logging
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("compute-daemon")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://YOUR_COMPUTE_NODE_IP:11434")
DAEMON_PORT: int = int(os.getenv("DAEMON_PORT", "8100"))
CONTROLLER_URL: str = os.getenv("CONTROLLER_URL", "http://YOUR_COMPUTE_NODE_IP:8050")
HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
IDLE_TIMEOUT: int = int(os.getenv("IDLE_TIMEOUT", "1800"))  # 30 min

VRAM_TOTAL_GB: float = 32.0
VRAM_RESERVE_GB: float = 4.0
VRAM_BUDGET_GB: float = VRAM_TOTAL_GB - VRAM_RESERVE_GB  # 28 GB nutzbar

# ---------------------------------------------------------------------------
# Modell-Katalog mit geschaetztem VRAM-Bedarf
# ---------------------------------------------------------------------------

class Tier(IntEnum):
    ALWAYS_WARM = 1   # Immer geladen
    ON_DEMAND_BIG = 2  # Grosse Modelle, on-demand
    ON_DEMAND_SMALL = 3  # Kleine Modelle, schnell ladbar


@dataclass
class ModelSpec:
    name: str
    tier: Tier
    vram_gb: float  # Geschaetzter VRAM-Bedarf
    tags: list[str] = field(default_factory=list)


MODEL_CATALOG: dict[str, ModelSpec] = {
    # Tier 1 — immer warm
    "qwen3.5:9b": ModelSpec("qwen3.5:9b", Tier.ALWAYS_WARM, 6.0, ["allrounder"]),

    # Tier 2 — on-demand gross (nie beide gleichzeitig!)
    "huihui_ai/deepseek-r1-abliterated:32b": ModelSpec(
        "huihui_ai/deepseek-r1-abliterated:32b", Tier.ON_DEMAND_BIG, 18.0, ["reasoning"]
    ),
    "huihui_ai/qwen3-abliterated:32b": ModelSpec(
        "huihui_ai/qwen3-abliterated:32b", Tier.ON_DEMAND_BIG, 18.0, ["reasoning"]
    ),
    "huihui_ai/qwen3-coder-abliterated:30b": ModelSpec(
        "huihui_ai/qwen3-coder-abliterated:30b", Tier.ON_DEMAND_BIG, 17.0, ["coding"]
    ),
    "huihui_ai/gemma3-abliterated:27b": ModelSpec(
        "huihui_ai/gemma3-abliterated:27b", Tier.ON_DEMAND_BIG, 15.0, ["general"]
    ),
    "huihui_ai/mistral-small-abliterated:24b": ModelSpec(
        "huihui_ai/mistral-small-abliterated:24b", Tier.ON_DEMAND_BIG, 14.0, ["general"]
    ),

    # Tier 2/3 — mittelgross
    "huihui_ai/phi4-abliterated:14b": ModelSpec(
        "huihui_ai/phi4-abliterated:14b", Tier.ON_DEMAND_SMALL, 8.5, ["reasoning"]
    ),
    "huihui_ai/gemma3-abliterated:12b": ModelSpec(
        "huihui_ai/gemma3-abliterated:12b", Tier.ON_DEMAND_SMALL, 7.5, ["general"]
    ),
    "nemotron:latest": ModelSpec("nemotron:latest", Tier.ON_DEMAND_SMALL, 5.0, ["general"]),
    "nemotron-3-nano:latest": ModelSpec("nemotron-3-nano:latest", Tier.ON_DEMAND_SMALL, 5.0, ["nano"]),

    # Tier 3 — klein, schnell ladbar
    "way2agi-orchestrator:latest": ModelSpec(
        "way2agi-orchestrator:latest", Tier.ON_DEMAND_SMALL, 5.0, ["orchestrator"]
    ),
    "elias-consciousness:latest": ModelSpec(
        "elias-consciousness:latest", Tier.ON_DEMAND_SMALL, 5.0, ["consciousness"]
    ),
}

# ---------------------------------------------------------------------------
# Pydantic Models fuer API
# ---------------------------------------------------------------------------

class InferenceRequest(BaseModel):
    model: str
    prompt: str
    system: Optional[str] = None
    options: dict = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)  # 1=hoechste Prioritaet
    stream: bool = False


class InferenceResponse(BaseModel):
    model: str
    response: str
    total_duration_ms: float
    eval_count: int = 0
    queue_wait_ms: float = 0.0


class WarmupRequest(BaseModel):
    model: str


class UnloadRequest(BaseModel):
    model: str


class StatusResponse(BaseModel):
    hostname: str
    gpu_name: str
    vram_total_gb: float
    vram_used_gb: float
    vram_free_gb: float
    ram_total_gb: float
    ram_used_gb: float
    ram_free_gb: float
    loaded_models: list[dict]
    uptime_seconds: float
    total_requests: int
    active_jobs: int
    queue_depth: int


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    ollama_reachable: bool
    gpu_available: bool
    vram_pressure: float  # 0.0 - 1.0
    loaded_models: int
    uptime_seconds: float


# ---------------------------------------------------------------------------
# Job Queue mit Prioritaet
# ---------------------------------------------------------------------------

@dataclass(order=True)
class PriorityJob:
    priority: int
    timestamp: float = field(compare=True)
    request: InferenceRequest = field(compare=False)
    future: asyncio.Future = field(compare=False, repr=False)


# ---------------------------------------------------------------------------
# Compute Manager — Kern-Logik
# ---------------------------------------------------------------------------

class ComputeManager:
    def __init__(self) -> None:
        self.start_time: float = time.time()
        self.total_requests: int = 0
        self.active_jobs: int = 0
        self.last_request_time: float = time.time()
        self.model_usage_count: dict[str, int] = defaultdict(int)
        self.loaded_models: dict[str, float] = {}  # model_name -> vram_gb
        self._queue: asyncio.PriorityQueue[PriorityJob] = asyncio.PriorityQueue()
        self._worker_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._shutdown: bool = False

    # --- Lifecycle ---

    async def startup(self) -> None:
        log.info("Compute Manager startet...")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))

        # Ollama erreichbar?
        if not await self._ping_ollama():
            log.error("Ollama nicht erreichbar unter %s", OLLAMA_URL)
            log.error("Daemon startet trotzdem — Ollama wird regelmaessig geprueft.")

        # Aktuell geladene Modelle von Ollama abfragen
        await self._sync_loaded_models()

        # Tier-1 Modelle aufwaermen
        for name, spec in MODEL_CATALOG.items():
            if spec.tier == Tier.ALWAYS_WARM:
                await self.warmup_model(name)

        # Background Workers starten
        self._worker_task = asyncio.create_task(self._job_worker())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._idle_task = asyncio.create_task(self._idle_monitor())

        # Beim Controller registrieren
        await self._register_at_controller()

        log.info("Compute Manager bereit. Port %d, Budget %.1fGB VRAM",
                 DAEMON_PORT, VRAM_BUDGET_GB)

    async def shutdown(self) -> None:
        log.info("Compute Manager faehrt herunter...")
        self._shutdown = True
        for task in [self._worker_task, self._heartbeat_task, self._idle_task]:
            if task:
                task.cancel()
        if self._http:
            await self._http.aclose()
        log.info("Shutdown abgeschlossen.")

    # --- Ollama Kommunikation ---

    async def _ping_ollama(self) -> bool:
        try:
            resp = await self._http.get(f"{OLLAMA_URL}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def _sync_loaded_models(self) -> None:
        """Fragt Ollama nach aktuell geladenen Modellen."""
        try:
            resp = await self._http.get(f"{OLLAMA_URL}/api/ps")
            if resp.status_code == 200:
                data = resp.json()
                self.loaded_models.clear()
                for m in data.get("models", []):
                    name = m.get("name", "")
                    size_bytes = m.get("size_vram", m.get("size", 0))
                    size_gb = size_bytes / (1024 ** 3)
                    self.loaded_models[name] = size_gb
                log.info("Geladene Modelle synchronisiert: %s",
                         {k: f"{v:.1f}GB" for k, v in self.loaded_models.items()})
        except Exception as e:
            log.warning("Konnte geladene Modelle nicht abfragen: %s", e)

    async def _ollama_generate(self, req: InferenceRequest) -> dict:
        """Sendet Generate-Request an Ollama."""
        payload = {
            "model": req.model,
            "prompt": req.prompt,
            "stream": False,
            "options": req.options,
        }
        if req.system:
            payload["system"] = req.system

        resp = await self._http.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=300.0,
        )
        resp.raise_for_status()
        return resp.json()

    async def _ollama_load(self, model: str) -> bool:
        """Laedt ein Modell in Ollama (leerer Prompt = nur laden)."""
        try:
            log.info("Lade Modell: %s", model)
            resp = await self._http.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": "", "stream": False, "keep_alive": "30m"},
                timeout=120.0,
            )
            if resp.status_code == 200:
                spec = MODEL_CATALOG.get(model)
                vram = spec.vram_gb if spec else 5.0
                self.loaded_models[model] = vram
                log.info("Modell geladen: %s (~%.1fGB)", model, vram)
                return True
            else:
                log.error("Fehler beim Laden von %s: %d", model, resp.status_code)
                return False
        except Exception as e:
            log.error("Fehler beim Laden von %s: %s", model, e)
            return False

    async def _ollama_unload(self, model: str) -> bool:
        """Entlaedt ein Modell aus Ollama."""
        try:
            log.info("Entlade Modell: %s", model)
            resp = await self._http.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": "", "stream": False, "keep_alive": "0"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                self.loaded_models.pop(model, None)
                log.info("Modell entladen: %s", model)
                return True
            else:
                log.error("Fehler beim Entladen von %s: %d", model, resp.status_code)
                return False
        except Exception as e:
            log.error("Fehler beim Entladen von %s: %s", model, e)
            return False

    # --- VRAM Management ---

    def _used_vram(self) -> float:
        return sum(self.loaded_models.values())

    def _free_vram(self) -> float:
        return VRAM_BUDGET_GB - self._used_vram()

    def _model_vram(self, model: str) -> float:
        spec = MODEL_CATALOG.get(model)
        return spec.vram_gb if spec else 5.0

    async def _ensure_vram_for(self, model: str) -> bool:
        """Stellt sicher, dass genug VRAM fuer das Modell frei ist.

        Entlaedt bei Bedarf niedrig-priorisierte Modelle.
        """
        if model in self.loaded_models:
            return True  # Schon geladen

        needed = self._model_vram(model)
        free = self._free_vram()

        if free >= needed:
            return True  # Genug Platz

        # VRAM freimachen — entlade nach Prioritaet (Tier 3 zuerst, dann 2)
        # Tier 1 wird NIE entladen
        to_free = needed - free
        freed = 0.0

        # Kandidaten sortieren: Tier absteigend, Usage aufsteigend
        candidates = []
        for loaded_name, loaded_vram in self.loaded_models.items():
            if loaded_name == model:
                continue
            spec = MODEL_CATALOG.get(loaded_name)
            tier = spec.tier if spec else Tier.ON_DEMAND_SMALL
            if tier == Tier.ALWAYS_WARM:
                continue  # Tier 1 nie entladen
            usage = self.model_usage_count.get(loaded_name, 0)
            candidates.append((tier, usage, loaded_name, loaded_vram))

        # Hoehere Tier-Nummer (=niedriger Prioritaet) zuerst, dann weniger genutzte
        candidates.sort(key=lambda x: (-x[0], x[1]))

        for tier_val, usage, cand_name, cand_vram in candidates:
            if freed >= to_free:
                break
            ok = await self._ollama_unload(cand_name)
            if ok:
                freed += cand_vram

        return self._free_vram() >= needed

    # --- Tier-2 Konflikt-Check ---

    def _is_big_model(self, model: str) -> bool:
        spec = MODEL_CATALOG.get(model)
        return spec is not None and spec.tier == Tier.ON_DEMAND_BIG

    def _loaded_big_models(self) -> list[str]:
        return [m for m in self.loaded_models if self._is_big_model(m)]

    async def _handle_big_model_conflict(self, model: str) -> bool:
        """Nie zwei Tier-2 Modelle gleichzeitig."""
        if not self._is_big_model(model):
            return True

        loaded_bigs = self._loaded_big_models()
        for big in loaded_bigs:
            if big != model:
                log.info("Tier-2 Konflikt: %s entladen fuer %s", big, model)
                await self._ollama_unload(big)

        return True

    # --- Warmup / Unload API ---

    async def warmup_model(self, model: str) -> bool:
        if model in self.loaded_models:
            log.info("Modell %s ist bereits geladen.", model)
            return True

        await self._handle_big_model_conflict(model)
        space_ok = await self._ensure_vram_for(model)
        if not space_ok:
            log.error("Nicht genug VRAM fuer %s (brauche %.1fGB, frei: %.1fGB)",
                      model, self._model_vram(model), self._free_vram())
            return False

        return await self._ollama_load(model)

    async def unload_model(self, model: str) -> bool:
        spec = MODEL_CATALOG.get(model)
        if spec and spec.tier == Tier.ALWAYS_WARM:
            log.warning("Tier-1 Modell %s wird normalerweise nicht entladen.", model)
        return await self._ollama_unload(model)

    # --- Inference ---

    async def run_inference(self, req: InferenceRequest) -> InferenceResponse:
        self.total_requests += 1
        self.last_request_time = time.time()
        self.model_usage_count[req.model] += 1

        # VRAM sicherstellen
        await self._handle_big_model_conflict(req.model)
        space_ok = await self._ensure_vram_for(req.model)
        if not space_ok:
            raise HTTPException(
                status_code=503,
                detail=f"Nicht genug VRAM fuer {req.model} "
                       f"(brauche {self._model_vram(req.model):.1f}GB, "
                       f"frei: {self._free_vram():.1f}GB)"
            )

        # Modell laden falls noetig
        if req.model not in self.loaded_models:
            ok = await self._ollama_load(req.model)
            if not ok:
                raise HTTPException(status_code=500, detail=f"Konnte {req.model} nicht laden")

        # Inferenz ausfuehren
        t0 = time.time()
        self.active_jobs += 1
        try:
            result = await self._ollama_generate(req)
        finally:
            self.active_jobs -= 1

        duration_ms = (time.time() - t0) * 1000
        return InferenceResponse(
            model=req.model,
            response=result.get("response", ""),
            total_duration_ms=duration_ms,
            eval_count=result.get("eval_count", 0),
        )

    # --- Priority Queue Worker ---

    async def enqueue_job(self, req: InferenceRequest) -> InferenceResponse:
        """Fuegt Job in Priority Queue ein und wartet auf Ergebnis."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        job = PriorityJob(
            priority=req.priority,
            timestamp=time.time(),
            request=req,
            future=future,
        )
        await self._queue.put(job)
        log.info("Job eingereiht: model=%s prio=%d queue_depth=%d",
                 req.model, req.priority, self._queue.qsize())
        return await future

    async def _job_worker(self) -> None:
        """Verarbeitet Jobs aus der Priority Queue."""
        log.info("Job Worker gestartet.")
        while not self._shutdown:
            try:
                job: PriorityJob = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            queue_wait = (time.time() - job.timestamp) * 1000
            try:
                result = await self.run_inference(job.request)
                result.queue_wait_ms = queue_wait
                job.future.set_result(result)
            except Exception as e:
                if not job.future.done():
                    job.future.set_exception(e)

        log.info("Job Worker gestoppt.")

    # --- Background Tasks ---

    async def _heartbeat_loop(self) -> None:
        """Sendet regelmaessig Status an den Inference Node Controller."""
        log.info("Heartbeat Loop gestartet (Intervall: %ds)", HEARTBEAT_INTERVAL)
        while not self._shutdown:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Heartbeat fehlgeschlagen: %s", e)

    async def _send_heartbeat(self) -> None:
        status = self._build_status()
        health = self._build_health(await self._ping_ollama())
        payload = {
            "node": "desktop",
            "gpu": "RTX 5090",
            "vram_total_gb": VRAM_TOTAL_GB,
            "vram_used_gb": self._used_vram(),
            "vram_free_gb": self._free_vram(),
            "loaded_models": list(self.loaded_models.keys()),
            "active_jobs": self.active_jobs,
            "queue_depth": self._queue.qsize(),
            "health": health.status,
            "uptime": time.time() - self.start_time,
            "total_requests": self.total_requests,
            "endpoint": f"http://YOUR_COMPUTE_NODE_IP:{DAEMON_PORT}",
        }
        try:
            resp = await self._http.post(
                f"{CONTROLLER_URL}/heartbeat",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code != 200:
                log.warning("Controller Heartbeat: HTTP %d", resp.status_code)
        except Exception as e:
            log.debug("Controller nicht erreichbar: %s", e)

    async def _register_at_controller(self) -> None:
        """Registriert diesen Node beim Inference Node Controller."""
        payload = {
            "node": "desktop",
            "gpu": "RTX 5090",
            "vram_total_gb": VRAM_TOTAL_GB,
            "endpoint": f"http://YOUR_COMPUTE_NODE_IP:{DAEMON_PORT}",
            "models": list(MODEL_CATALOG.keys()),
            "capabilities": ["inference", "large-models", "coding", "reasoning"],
        }
        try:
            resp = await self._http.post(
                f"{CONTROLLER_URL}/register",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code == 200:
                log.info("Beim Controller registriert: %s", CONTROLLER_URL)
            else:
                log.warning("Controller-Registrierung: HTTP %d", resp.status_code)
        except Exception as e:
            log.warning("Controller nicht erreichbar fuer Registrierung: %s", e)

    async def _idle_monitor(self) -> None:
        """Entlaedt Tier-2 Modelle nach Idle-Timeout."""
        log.info("Idle Monitor gestartet (Timeout: %ds)", IDLE_TIMEOUT)
        while not self._shutdown:
            try:
                await asyncio.sleep(60)  # Jede Minute pruefen
                idle_seconds = time.time() - self.last_request_time
                if idle_seconds >= IDLE_TIMEOUT:
                    # Tier 2 entladen
                    big_loaded = self._loaded_big_models()
                    if big_loaded:
                        log.info("Idle seit %.0fs — entlade Tier-2 Modelle: %s",
                                 idle_seconds, big_loaded)
                        for m in big_loaded:
                            await self._ollama_unload(m)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Idle Monitor Fehler: %s", e)

    # --- Status Builders ---

    def _build_status(self) -> StatusResponse:
        ram = psutil.virtual_memory()
        return StatusResponse(
            hostname="desktop-rtx5090",
            gpu_name="NVIDIA RTX 5090",
            vram_total_gb=VRAM_TOTAL_GB,
            vram_used_gb=self._used_vram(),
            vram_free_gb=self._free_vram(),
            ram_total_gb=round(ram.total / (1024 ** 3), 1),
            ram_used_gb=round(ram.used / (1024 ** 3), 1),
            ram_free_gb=round(ram.available / (1024 ** 3), 1),
            loaded_models=[
                {"name": name, "vram_gb": round(vram, 1),
                 "tier": MODEL_CATALOG[name].tier if name in MODEL_CATALOG else 3,
                 "usage_count": self.model_usage_count.get(name, 0)}
                for name, vram in self.loaded_models.items()
            ],
            uptime_seconds=round(time.time() - self.start_time, 1),
            total_requests=self.total_requests,
            active_jobs=self.active_jobs,
            queue_depth=self._queue.qsize(),
        )

    def _build_health(self, ollama_ok: bool) -> HealthResponse:
        vram_pressure = self._used_vram() / VRAM_BUDGET_GB if VRAM_BUDGET_GB > 0 else 0.0
        if not ollama_ok:
            status = "unhealthy"
        elif vram_pressure > 0.95:
            status = "degraded"
        else:
            status = "healthy"

        return HealthResponse(
            status=status,
            ollama_reachable=ollama_ok,
            gpu_available=True,
            vram_pressure=round(vram_pressure, 3),
            loaded_models=len(self.loaded_models),
            uptime_seconds=round(time.time() - self.start_time, 1),
        )


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Way2AGI Desktop Compute Daemon",
    version="1.0.0",
    description="GPU Resource Manager fuer RTX 5090",
)
manager = ComputeManager()


@app.on_event("startup")
async def on_startup() -> None:
    await manager.startup()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await manager.shutdown()


# --- Endpoints ---

@app.post("/inference", response_model=InferenceResponse)
async def inference(req: InferenceRequest):
    """Inferenz-Job annehmen. Wird in Priority Queue eingereiht."""
    try:
        return await manager.enqueue_job(req)
    except HTTPException:
        raise
    except Exception as e:
        log.error("Inferenz fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status", response_model=StatusResponse)
async def status():
    """Aktueller VRAM/RAM/GPU Status und geladene Modelle."""
    return manager._build_status()


@app.post("/warmup")
async def warmup(req: WarmupRequest):
    """Modell vorladen (ohne Inferenz)."""
    ok = await manager.warmup_model(req.model)
    if ok:
        return {"status": "loaded", "model": req.model,
                "vram_used_gb": round(manager._used_vram(), 1),
                "vram_free_gb": round(manager._free_vram(), 1)}
    raise HTTPException(status_code=500, detail=f"Konnte {req.model} nicht laden")


@app.post("/unload")
async def unload(req: UnloadRequest):
    """Modell entladen und VRAM freigeben."""
    ok = await manager.unload_model(req.model)
    if ok:
        return {"status": "unloaded", "model": req.model,
                "vram_used_gb": round(manager._used_vram(), 1),
                "vram_free_gb": round(manager._free_vram(), 1)}
    raise HTTPException(status_code=500, detail=f"Konnte {req.model} nicht entladen")


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health Check fuer Inference Node Controller."""
    ollama_ok = await manager._ping_ollama()
    return manager._build_health(ollama_ok)


@app.post("/register")
async def register():
    """Manuell beim Controller re-registrieren."""
    await manager._register_at_controller()
    return {"status": "registered", "controller": CONTROLLER_URL}


@app.get("/models")
async def list_models():
    """Zeigt den kompletten Modell-Katalog mit Tier und VRAM-Bedarf."""
    models = []
    for name, spec in MODEL_CATALOG.items():
        models.append({
            "name": name,
            "tier": spec.tier,
            "vram_gb": spec.vram_gb,
            "tags": spec.tags,
            "loaded": name in manager.loaded_models,
            "usage_count": manager.model_usage_count.get(name, 0),
        })
    return {"models": models, "total": len(models)}


@app.get("/vram")
async def vram_summary():
    """Kompakte VRAM-Uebersicht."""
    return {
        "total_gb": VRAM_TOTAL_GB,
        "budget_gb": VRAM_BUDGET_GB,
        "used_gb": round(manager._used_vram(), 1),
        "free_gb": round(manager._free_vram(), 1),
        "reserve_gb": VRAM_RESERVE_GB,
        "loaded": {name: f"{vram:.1f}GB" for name, vram in manager.loaded_models.items()},
        "utilization_pct": round((manager._used_vram() / VRAM_BUDGET_GB) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=" * 60)
    log.info("Way2AGI Desktop Compute Daemon v1.0.0")
    log.info("GPU: RTX 5090 (32GB VRAM, Budget: %.0fGB)", VRAM_BUDGET_GB)
    log.info("Ollama: %s", OLLAMA_URL)
    log.info("Controller: %s", CONTROLLER_URL)
    log.info("Port: %d", DAEMON_PORT)
    log.info("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=DAEMON_PORT,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
