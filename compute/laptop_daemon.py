#!/usr/bin/env python3
"""
Way2AGI Laptop Daemon (Lightweight)
====================================
Leichtgewichtiger Compute-Node fuer Windows Laptops mit NPU (Phi Silica).
Nutzt die NPU fuer lokale Inferenz ohne GPU-Kosten.

Dependencies:
    pip install fastapi uvicorn httpx psutil pydantic

    Optional (Phi Silica / NPU):
        pip install onnxruntime-genai

    Optional (Ollama Fallback):
        Ollama installiert + kleines Modell (qwen3:1.7b, phi4-mini)

Starten:
    python laptop_daemon.py

Konfiguration ueber Umgebungsvariablen:
    DAEMON_PORT         (default: 8150)
    CONTROLLER_URL      (default: http://YOUR_CONTROLLER_IP:8050)
    OLLAMA_URL          (default: http://localhost:11434)
    HEARTBEAT_INTERVAL  (default: 60)
    IDLE_TIMEOUT        (default: 1800)
    PHI_SILICA_MODEL    (default: auto-detect)
"""

import asyncio
import ctypes
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Optional

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.environ.get("TEMP", "/tmp"), "laptop_daemon.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("laptop-daemon")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DAEMON_PORT: int = int(os.getenv("DAEMON_PORT", "8150"))
CONTROLLER_URL: str = os.getenv("CONTROLLER_URL", "http://YOUR_CONTROLLER_IP:8050")
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
IDLE_TIMEOUT: int = int(os.getenv("IDLE_TIMEOUT", "1800"))  # 30 min
PHI_SILICA_MODEL: str = os.getenv("PHI_SILICA_MODEL", "")

IS_WINDOWS = platform.system() == "Windows"

# Windows API Konstanten fuer SetThreadExecutionState
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040


# ---------------------------------------------------------------------------
# Inference Backend Enum
# ---------------------------------------------------------------------------

class InferenceBackend(str, Enum):
    PHI_SILICA = "phi_silica"
    OLLAMA = "ollama"
    NONE = "none"


# ---------------------------------------------------------------------------
# Phi Silica / ONNX Runtime GenAI Backend
# ---------------------------------------------------------------------------

class PhiSilicaBackend:
    """Phi Silica via onnxruntime-genai auf der NPU."""

    def __init__(self) -> None:
        self.available: bool = False
        self.model = None
        self.tokenizer = None
        self.model_path: str = ""
        self._og = None  # onnxruntime_genai module

    def probe(self) -> bool:
        """Prueft ob onnxruntime-genai und ein Phi-Modell verfuegbar sind."""
        try:
            import onnxruntime_genai as og
            self._og = og
            log.info("onnxruntime-genai gefunden: Version %s", og.__version__)
        except ImportError:
            log.info("onnxruntime-genai nicht installiert — Phi Silica nicht verfuegbar")
            return False

        # Modell-Pfad suchen
        model_path = self._find_model_path()
        if not model_path:
            log.warning("Kein Phi Silica Modell gefunden")
            return False

        self.model_path = model_path
        log.info("Phi Silica Modell gefunden: %s", model_path)
        return True

    def _find_model_path(self) -> str:
        """Sucht nach dem Phi Silica ONNX-Modell."""
        # Explizit konfiguriert?
        if PHI_SILICA_MODEL and os.path.isdir(PHI_SILICA_MODEL):
            return PHI_SILICA_MODEL

        # Standard-Pfade fuer Windows AI / Phi Silica
        search_paths = [
            # Windows AI Runtime Modelle
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows.AI\Models\phi-silica"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows.AI\Models\phi-silica-onnx"),
            # Manuell heruntergeladene Modelle
            os.path.expandvars(r"%USERPROFILE%\models\phi-silica"),
            os.path.expandvars(r"%USERPROFILE%\.cache\phi-silica"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Packages\Microsoft.Windows.AI*"),
            # Generische Orte
            r"C:\models\phi-silica",
            r"C:\AI\phi-silica",
        ]

        for path in search_paths:
            if os.path.isdir(path):
                # Pruefe ob ein genai_config.json existiert (ONNX GenAI Marker)
                if os.path.isfile(os.path.join(path, "genai_config.json")):
                    return path
                # Oder ein .onnx File
                for f in os.listdir(path):
                    if f.endswith(".onnx"):
                        return path

        return ""

    def load(self) -> bool:
        """Laedt das Phi Silica Modell in den Speicher."""
        if not self._og or not self.model_path:
            return False

        try:
            log.info("Lade Phi Silica Modell von %s ...", self.model_path)
            self.model = self._og.Model(self.model_path)
            self.tokenizer = self._og.Tokenizer(self.model)
            self.available = True
            log.info("Phi Silica Modell geladen und bereit")
            return True
        except Exception as e:
            log.error("Fehler beim Laden des Phi Silica Modells: %s", e)
            self.available = False
            return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Generiert Text mit Phi Silica."""
        if not self.available or not self.model or not self.tokenizer:
            raise RuntimeError("Phi Silica nicht verfuegbar")

        og = self._og

        # Chat-Format fuer Phi
        full_prompt = ""
        if system:
            full_prompt += f"<|system|>\n{system}<|end|>\n"
        full_prompt += f"<|user|>\n{prompt}<|end|>\n<|assistant|>\n"

        input_tokens = self.tokenizer.encode(full_prompt)

        params = og.GeneratorParams(self.model)
        params.set_search_options(
            max_length=len(input_tokens) + max_tokens,
            temperature=max(temperature, 0.01),  # 0 nicht erlaubt
            top_p=0.9,
            do_sample=temperature > 0.01,
        )
        params.input_ids = input_tokens

        generator = og.Generator(self.model, params)
        output_tokens = []

        while not generator.is_done():
            generator.compute_logits()
            generator.generate_next_token()
            token = generator.get_next_tokens()[0]
            output_tokens.append(token)

            if len(output_tokens) >= max_tokens:
                break

        response = self.tokenizer.decode(output_tokens)

        # Cleanup: End-Tokens entfernen
        for stop in ("<|end|>", "<|endoftext|>", "<|assistant|>"):
            if stop in response:
                response = response.split(stop)[0]

        return response.strip()

    def unload(self) -> None:
        """Gibt Modell-Speicher frei."""
        self.model = None
        self.tokenizer = None
        self.available = False
        log.info("Phi Silica Modell entladen")


# ---------------------------------------------------------------------------
# Windows Keep-Alive Mechanismus
# ---------------------------------------------------------------------------

class KeepAliveManager:
    """Verhindert Windows Sleep/Standby waehrend der Daemon aktiv ist."""

    def __init__(self) -> None:
        self.active: bool = False
        self.last_activity: float = time.time()
        self._original_power_plan: Optional[str] = None
        self._idle_check_task: Optional[asyncio.Task] = None

    def activate(self) -> dict[str, Any]:
        """Aktiviert Keep-Alive: verhindert Sleep, setzt Power Plan."""
        self.last_activity = time.time()

        if self.active:
            return {"status": "already_active", "since": self.last_activity}

        result: dict[str, Any] = {"status": "activated"}

        # 1. SetThreadExecutionState — verhindert Sleep
        if IS_WINDOWS:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
                result["execution_state"] = "set"
                log.info("Windows Sleep-Prevention aktiviert (SetThreadExecutionState)")
            except Exception as e:
                result["execution_state_error"] = str(e)
                log.warning("SetThreadExecutionState fehlgeschlagen: %s", e)

            # 2. Power Plan auf High Performance setzen
            try:
                self._original_power_plan = self._get_active_power_plan()
                # GUID fuer High Performance
                hp_guid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
                subprocess.run(
                    ["powercfg", "/setactive", hp_guid],
                    capture_output=True, timeout=10,
                )
                result["power_plan"] = "high_performance"
                log.info("Power Plan auf High Performance gesetzt")
            except Exception as e:
                result["power_plan_error"] = str(e)
                log.warning("Power Plan Wechsel fehlgeschlagen: %s", e)
        else:
            result["note"] = "Nicht Windows — Keep-Alive nur symbolisch"

        self.active = True
        return result

    def deactivate(self) -> dict[str, Any]:
        """Deaktiviert Keep-Alive: erlaubt Sleep, stellt Power Plan wieder her."""
        if not self.active:
            return {"status": "already_inactive"}

        result: dict[str, Any] = {"status": "deactivated"}

        if IS_WINDOWS:
            # 1. Sleep wieder erlauben
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                result["execution_state"] = "reset"
                log.info("Windows Sleep-Prevention deaktiviert")
            except Exception as e:
                result["execution_state_error"] = str(e)

            # 2. Power Plan zuruecksetzen
            if self._original_power_plan:
                try:
                    subprocess.run(
                        ["powercfg", "/setactive", self._original_power_plan],
                        capture_output=True, timeout=10,
                    )
                    result["power_plan"] = "restored"
                    log.info("Power Plan wiederhergestellt: %s", self._original_power_plan)
                except Exception as e:
                    result["power_plan_error"] = str(e)

        self.active = False
        return result

    def touch(self) -> None:
        """Aktualisiert den letzten Aktivitaets-Timestamp."""
        self.last_activity = time.time()

    def idle_seconds(self) -> float:
        """Sekunden seit letzter Aktivitaet."""
        return time.time() - self.last_activity

    @staticmethod
    def _get_active_power_plan() -> Optional[str]:
        """Liest den aktuellen Power Plan GUID aus."""
        if not IS_WINDOWS:
            return None
        try:
            result = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True, text=True, timeout=10,
            )
            # Output: "Energieschema-GUID: 381b4222-..."
            for part in result.stdout.split():
                if len(part) == 36 and part.count("-") == 4:
                    return part
        except Exception:
            pass
        return None

    async def idle_monitor_loop(self, timeout: int) -> None:
        """Deaktiviert Keep-Alive nach Idle-Timeout."""
        while True:
            try:
                await asyncio.sleep(60)
                if self.active and self.idle_seconds() >= timeout:
                    log.info(
                        "Idle seit %.0fs (Timeout: %ds) — deaktiviere Keep-Alive",
                        self.idle_seconds(), timeout,
                    )
                    self.deactivate()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Idle Monitor Fehler: %s", e)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class InferenceRequest(BaseModel):
    prompt: str
    model: Optional[str] = None  # None = auto (Phi Silica -> Ollama)
    system: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1024
    priority: int = Field(default=5, ge=1, le=10)


class InferenceResponse(BaseModel):
    response: str
    backend: str  # "phi_silica" | "ollama"
    model: str
    duration_ms: float
    tokens_generated: int = 0


class StatusResponse(BaseModel):
    hostname: str
    platform: str
    cpu_percent: float
    ram_total_gb: float
    ram_used_gb: float
    ram_free_gb: float
    npu_available: bool
    npu_model: str
    ollama_available: bool
    ollama_models: list[str]
    active_backend: str
    keepalive_active: bool
    idle_seconds: float
    uptime_seconds: float
    total_requests: int
    active_jobs: int


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    backends: dict[str, bool]
    uptime_seconds: float
    models: list[str]


class KeepAliveRequest(BaseModel):
    action: str = "activate"  # "activate" | "deactivate" | "touch"


# ---------------------------------------------------------------------------
# Laptop Daemon Manager
# ---------------------------------------------------------------------------

class LaptopDaemonManager:
    """Kern-Logik des Laptop Daemons."""

    def __init__(self) -> None:
        self.start_time: float = time.time()
        self.total_requests: int = 0
        self.active_jobs: int = 0
        self.last_request_time: float = time.time()
        self.request_stats: dict[str, int] = defaultdict(int)  # backend -> count

        self.phi_silica = PhiSilicaBackend()
        self.keepalive = KeepAliveManager()

        self._ollama_available: bool = False
        self._ollama_models: list[str] = []
        self._http: Optional[httpx.AsyncClient] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False

    # --- Lifecycle ---

    async def startup(self) -> None:
        log.info("Laptop Daemon startet...")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

        # 1. Phi Silica proben
        if self.phi_silica.probe():
            self.phi_silica.load()

        # 2. Ollama proben
        await self._probe_ollama()

        # 3. Backend-Status loggen
        backend = self._active_backend()
        if backend == InferenceBackend.NONE:
            log.warning("KEIN Inferenz-Backend verfuegbar! Nur Status-API aktiv.")
        else:
            log.info("Aktives Backend: %s", backend.value)

        # 4. Background Tasks starten
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._idle_task = asyncio.create_task(
            self.keepalive.idle_monitor_loop(IDLE_TIMEOUT)
        )

        # 5. Beim Controller registrieren
        await self._register_at_controller()

        log.info("Laptop Daemon bereit auf Port %d", DAEMON_PORT)

    async def shutdown(self) -> None:
        log.info("Laptop Daemon faehrt herunter...")
        self._shutdown = True

        # Keep-Alive deaktivieren
        self.keepalive.deactivate()

        # Phi Silica entladen
        self.phi_silica.unload()

        # Background Tasks stoppen
        for task in [self._heartbeat_task, self._idle_task]:
            if task:
                task.cancel()

        if self._http:
            await self._http.aclose()

        log.info("Shutdown abgeschlossen.")

    # --- Backend Selection ---

    def _active_backend(self) -> InferenceBackend:
        """Bestimmt das aktuell beste verfuegbare Backend."""
        if self.phi_silica.available:
            return InferenceBackend.PHI_SILICA
        if self._ollama_available:
            return InferenceBackend.OLLAMA
        return InferenceBackend.NONE

    # --- Ollama ---

    async def _probe_ollama(self) -> None:
        """Prueft ob Ollama lokal laeuft und welche Modelle verfuegbar sind."""
        try:
            resp = await self._http.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                self._ollama_models = [m["name"] for m in data.get("models", [])]
                self._ollama_available = True
                log.info("Ollama verfuegbar — Modelle: %s", self._ollama_models)
            else:
                self._ollama_available = False
                log.info("Ollama antwortet mit HTTP %d", resp.status_code)
        except Exception:
            self._ollama_available = False
            log.info("Ollama nicht erreichbar unter %s", OLLAMA_URL)

    async def _ollama_generate(
        self,
        prompt: str,
        model: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Generiert Text ueber Ollama."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        resp = await self._http.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Inference (Fallback Chain) ---

    async def run_inference(self, req: InferenceRequest) -> InferenceResponse:
        """
        Fuehrt Inferenz aus mit Fallback-Chain:
        Phi Silica -> Ollama -> Error
        """
        self.total_requests += 1
        self.last_request_time = time.time()
        self.keepalive.touch()

        # Keep-Alive aktivieren bei Request
        if not self.keepalive.active:
            self.keepalive.activate()

        self.active_jobs += 1
        try:
            return await self._do_inference(req)
        finally:
            self.active_jobs -= 1

    async def _do_inference(self, req: InferenceRequest) -> InferenceResponse:
        """Interne Inferenz-Logik mit Fallback."""

        # Explizites Ollama-Modell angefordert?
        if req.model and req.model != "phi-silica":
            if self._ollama_available:
                return await self._inference_ollama(req)
            raise HTTPException(
                503, f"Ollama nicht verfuegbar fuer Modell '{req.model}'"
            )

        # 1. Phi Silica versuchen
        if self.phi_silica.available:
            try:
                return await self._inference_phi_silica(req)
            except Exception as e:
                log.warning("Phi Silica Fehler, Fallback auf Ollama: %s", e)

        # 2. Ollama Fallback
        if self._ollama_available:
            try:
                return await self._inference_ollama(req)
            except Exception as e:
                log.error("Ollama Fallback fehlgeschlagen: %s", e)

        # 3. Kein Backend verfuegbar
        raise HTTPException(
            503,
            "Kein Inferenz-Backend verfuegbar. "
            "Weder Phi Silica noch Ollama erreichbar.",
        )

    async def _inference_phi_silica(self, req: InferenceRequest) -> InferenceResponse:
        """Inferenz ueber Phi Silica (NPU)."""
        t0 = time.time()

        # Phi Silica ist synchron — in Thread-Pool ausfuehren
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.phi_silica.generate(
                prompt=req.prompt,
                system=req.system,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            ),
        )

        duration_ms = (time.time() - t0) * 1000
        self.request_stats["phi_silica"] += 1

        return InferenceResponse(
            response=response,
            backend="phi_silica",
            model="phi-silica",
            duration_ms=round(duration_ms, 1),
            tokens_generated=len(response.split()),  # Grobe Schaetzung
        )

    async def _inference_ollama(self, req: InferenceRequest) -> InferenceResponse:
        """Inferenz ueber Ollama."""
        # Modell auswaehlen: explizit oder erstes verfuegbares kleines Modell
        model = req.model
        if not model or model == "phi-silica":
            # Bevorzugte kleine Modelle
            preferred = ["qwen3:1.7b", "phi4-mini", "phi3-mini", "gemma3:1b"]
            model = None
            for pref in preferred:
                for available in self._ollama_models:
                    if pref in available:
                        model = available
                        break
                if model:
                    break
            if not model and self._ollama_models:
                model = self._ollama_models[0]
            if not model:
                raise HTTPException(503, "Keine Ollama-Modelle verfuegbar")

        t0 = time.time()
        result = await self._ollama_generate(
            prompt=req.prompt,
            model=model,
            system=req.system,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        duration_ms = (time.time() - t0) * 1000
        self.request_stats["ollama"] += 1

        return InferenceResponse(
            response=result.get("response", ""),
            backend="ollama",
            model=model,
            duration_ms=round(duration_ms, 1),
            tokens_generated=result.get("eval_count", 0),
        )

    # --- Controller Registration ---

    async def _register_at_controller(self) -> None:
        """Registriert sich beim Jetson Controller."""
        my_ip = self._get_local_ip()
        models = []
        if self.phi_silica.available:
            models.append("phi-silica")
        models.extend(self._ollama_models)

        payload = {
            "name": f"laptop-{socket.gethostname().lower()}",
            "url": f"http://{my_ip}:{DAEMON_PORT}",
            "node_type": "compute",
            "vram": 0,  # NPU, kein diskreter VRAM
            "models": models,
        }

        try:
            resp = await self._http.post(
                f"{CONTROLLER_URL}/nodes/register",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code == 200:
                log.info(
                    "Beim Controller registriert: %s (IP: %s)",
                    CONTROLLER_URL, my_ip,
                )
            else:
                log.warning("Controller-Registrierung: HTTP %d", resp.status_code)
        except Exception as e:
            log.warning("Controller nicht erreichbar: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Sendet regelmaessig Heartbeat an den Controller."""
        log.info("Heartbeat Loop gestartet (Intervall: %ds)", HEARTBEAT_INTERVAL)
        while not self._shutdown:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self._send_heartbeat()
                # Ollama-Status regelmaessig pruefen
                await self._probe_ollama()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("Heartbeat Fehler: %s", e)

    async def _send_heartbeat(self) -> None:
        """Sendet Status an den Controller."""
        my_ip = self._get_local_ip()
        models = []
        if self.phi_silica.available:
            models.append("phi-silica")
        models.extend(self._ollama_models)

        ram = psutil.virtual_memory()
        payload = {
            "node": f"laptop-{socket.gethostname().lower()}",
            "npu": "Phi Silica" if self.phi_silica.available else "none",
            "ram_total_gb": round(ram.total / (1024 ** 3), 1),
            "ram_used_gb": round(ram.used / (1024 ** 3), 1),
            "loaded_models": models,
            "active_jobs": self.active_jobs,
            "health": "healthy" if self._active_backend() != InferenceBackend.NONE else "degraded",
            "uptime": time.time() - self.start_time,
            "total_requests": self.total_requests,
            "endpoint": f"http://{my_ip}:{DAEMON_PORT}",
            "keepalive_active": self.keepalive.active,
            "idle_seconds": round(self.keepalive.idle_seconds(), 0),
        }

        try:
            resp = await self._http.post(
                f"{CONTROLLER_URL}/heartbeat",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code not in (200, 404):
                log.warning("Controller Heartbeat: HTTP %d", resp.status_code)
        except Exception as e:
            log.debug("Controller nicht erreichbar: %s", e)

    # --- Helpers ---

    @staticmethod
    def _get_local_ip() -> str:
        """Ermittelt die lokale IP-Adresse im Netzwerk."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("YOUR_CONTROLLER_IP", 80))  # Controller als Ziel
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def build_status(self) -> StatusResponse:
        """Baut die vollstaendige Status-Antwort."""
        ram = psutil.virtual_memory()
        return StatusResponse(
            hostname=socket.gethostname(),
            platform=f"{platform.system()} {platform.release()}",
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_total_gb=round(ram.total / (1024 ** 3), 1),
            ram_used_gb=round(ram.used / (1024 ** 3), 1),
            ram_free_gb=round(ram.available / (1024 ** 3), 1),
            npu_available=self.phi_silica.available,
            npu_model=self.phi_silica.model_path if self.phi_silica.available else "",
            ollama_available=self._ollama_available,
            ollama_models=self._ollama_models,
            active_backend=self._active_backend().value,
            keepalive_active=self.keepalive.active,
            idle_seconds=round(self.keepalive.idle_seconds(), 0),
            uptime_seconds=round(time.time() - self.start_time, 1),
            total_requests=self.total_requests,
            active_jobs=self.active_jobs,
        )

    def build_health(self) -> HealthResponse:
        """Baut die Health-Check Antwort."""
        backends = {
            "phi_silica": self.phi_silica.available,
            "ollama": self._ollama_available,
        }
        any_backend = any(backends.values())

        models = []
        if self.phi_silica.available:
            models.append("phi-silica")
        models.extend(self._ollama_models)

        return HealthResponse(
            status="healthy" if any_backend else "unhealthy",
            backends=backends,
            uptime_seconds=round(time.time() - self.start_time, 1),
            models=models,
        )


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

manager = LaptopDaemonManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown."""
    await manager.startup()
    yield
    await manager.shutdown()


app = FastAPI(
    title="Way2AGI Laptop Daemon",
    description=(
        "Leichtgewichtiger Compute-Node fuer Windows Laptops mit NPU (Phi Silica). "
        "Fallback auf Ollama mit kleinen Modellen."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# --- Endpoints ---

@app.post("/inference", response_model=InferenceResponse)
async def inference(req: InferenceRequest):
    """
    Inferenz-Endpoint.
    Fallback-Chain: Phi Silica (NPU) -> Ollama -> Error.
    """
    try:
        return await manager.run_inference(req)
    except HTTPException:
        raise
    except Exception as e:
        log.error("Inferenz fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status", response_model=StatusResponse)
async def status():
    """System-Status: CPU, RAM, NPU, Backends, Keep-Alive."""
    return manager.build_status()


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health Check fuer den Jetson Controller."""
    return manager.build_health()


@app.post("/register")
async def register():
    """Manuell beim Controller re-registrieren."""
    await manager._register_at_controller()
    return {"status": "registered", "controller": CONTROLLER_URL}


@app.post("/keepalive")
async def keepalive(req: KeepAliveRequest = KeepAliveRequest()):
    """
    Keep-Alive Steuerung.
    - activate: Verhindert Sleep, setzt High Performance Power Plan
    - deactivate: Erlaubt Sleep, stellt Power Plan wieder her
    - touch: Aktualisiert den Aktivitaets-Timestamp
    """
    if req.action == "activate":
        result = manager.keepalive.activate()
    elif req.action == "deactivate":
        result = manager.keepalive.deactivate()
    elif req.action == "touch":
        manager.keepalive.touch()
        result = {
            "status": "touched",
            "idle_seconds": round(manager.keepalive.idle_seconds(), 0),
        }
    else:
        raise HTTPException(400, f"Unbekannte Aktion: {req.action}")

    result["keepalive_active"] = manager.keepalive.active
    result["idle_seconds"] = round(manager.keepalive.idle_seconds(), 0)
    return result


@app.get("/backends")
async def backends():
    """Zeigt verfuegbare Backends und deren Status."""
    result: dict[str, Any] = {
        "active_backend": manager._active_backend().value,
        "phi_silica": {
            "available": manager.phi_silica.available,
            "model_path": manager.phi_silica.model_path,
        },
        "ollama": {
            "available": manager._ollama_available,
            "url": OLLAMA_URL,
            "models": manager._ollama_models,
        },
        "request_stats": dict(manager.request_stats),
    }
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=" * 60)
    log.info("Way2AGI Laptop Daemon v1.0.0")
    log.info("Platform: %s %s", platform.system(), platform.release())
    log.info("Hostname: %s", socket.gethostname())
    log.info("Port: %d", DAEMON_PORT)
    log.info("Controller: %s", CONTROLLER_URL)
    log.info("Ollama: %s", OLLAMA_URL)
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
