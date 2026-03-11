# core/micro_orchestrator.py
"""
Micro-Orchestrator — Lokaler Entscheider pro Geraet
=====================================================
Jedes Geraet (Jetson, Desktop, Laptop, S24) bekommt einen eigenen
Mini-Orchestrator der lokal entscheidet:
  - Welches Modell fuer den Task am besten ist
  - Ob der Task lokal ausfuehrbar ist
  - Eigene Health-Checks + Model Registry

Der zentrale Orchestrator fragt die Geraete nur noch:
  "Kannst du diesen Task? Wie schnell? Welches Modell?"

Inspiriert von Eriks Vision: Dezentrale Edge-Orchestrierung.
"""

import asyncio
import json
import logging
import os
import platform
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.micro_orch")


# ---------------------------------------------------------------------------
# Local Model Registry
# ---------------------------------------------------------------------------
@dataclass
class LocalModel:
    """A model available on this device."""
    name: str
    size_gb: float = 0.0
    speed_tok_s: float = 0.0      # Measured tokens/sec
    capabilities: List[str] = field(default_factory=list)  # code, reasoning, creative, system, memory
    max_context: int = 4096
    is_trained: bool = False       # Way2AGI fine-tuned?
    backend: str = "ollama"        # ollama | llama_cpp | cloud


@dataclass
class TaskBid:
    """A bid from this device to handle a task."""
    can_handle: bool
    model: str
    estimated_speed: float       # tok/s
    estimated_latency_ms: int    # Time to first token
    confidence: float            # 0-1 how well this model fits
    backend: str = "ollama"
    reason: str = ""


# ---------------------------------------------------------------------------
# Task Categories + Keywords (same as central, but local)
# ---------------------------------------------------------------------------
TASK_KEYWORDS = {
    "code": ["code", "programm", "script", "funktion", "bug", "fix", "python",
             "implement", "refactor", "debug", "api", "typescript"],
    "reasoning": ["warum", "erklaer", "analysier", "vergleich", "bewert", "denk",
                  "reason", "think", "math", "logik", "plan"],
    "creative": ["schreib", "text", "story", "gedicht", "zusammenfass",
                 "write", "creative", "prompt"],
    "memory": ["erinner", "speicher", "memory", "wann", "letzte", "frueher"],
    "system": ["status", "node", "health", "restart", "deploy", "update",
               "training", "train", "pipeline", "cron", "job", "config",
               "modell", "model", "liste", "verfuegbar", "starte", "stoppe"],
}


def classify_task(task: str) -> str:
    """Classify a task into a category."""
    task_lower = task.lower()
    scores = {cat: sum(1 for kw in kws if kw in task_lower)
              for cat, kws in TASK_KEYWORDS.items()}
    if not any(scores.values()):
        return "reasoning"
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Micro Orchestrator
# ---------------------------------------------------------------------------
class MicroOrchestrator:
    """
    Local orchestrator running on each device.

    Responsibilities:
    1. Discover local models (Ollama, llama.cpp)
    2. Accept task requests and bid on them
    3. Execute tasks using the best local model
    4. Report capabilities to central orchestrator
    5. Health monitoring
    """

    def __init__(
        self,
        device_name: str = "",
        ollama_url: str = "http://localhost:11434",
        llama_cpp_url: str = "",
        port: int = 8050,
    ):
        self.device_name = device_name or platform.node()
        self.ollama_url = ollama_url
        self.llama_cpp_url = llama_cpp_url
        self.port = port
        self.models: Dict[str, LocalModel] = {}
        self.last_discovery = 0.0
        self._started_at = time.time()

    # --- Model Discovery ---

    async def discover_models(self) -> Dict[str, LocalModel]:
        """Discover all available models on this device."""
        self.models = {}

        # Discover Ollama models
        try:
            req = urllib.request.Request(
                self.ollama_url + "/api/tags", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            for m in data.get("models", []):
                name = m.get("name", "")
                size_gb = round(m.get("size", 0) / 1e9, 1)
                is_trained = "way2agi" in name
                # Infer capabilities from model name
                caps = self._infer_capabilities(name, size_gb)
                self.models[name] = LocalModel(
                    name=name,
                    size_gb=size_gb,
                    capabilities=caps,
                    is_trained=is_trained,
                    backend="ollama",
                )
            log.info("Ollama: %d Modelle entdeckt", len(self.models))
        except Exception as e:
            log.warning("Ollama Discovery fehlgeschlagen: %s", e)

        # Discover llama.cpp
        if self.llama_cpp_url:
            try:
                req = urllib.request.Request(
                    self.llama_cpp_url + "/health", method="GET"
                )
                resp = urllib.request.urlopen(req, timeout=5)
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    self.models["llama-cpp-speculative"] = LocalModel(
                        name="nemotron-30b+4b-specdec",
                        size_gb=27.0,
                        speed_tok_s=31.0,
                        capabilities=["code", "reasoning", "creative", "system"],
                        backend="llama_cpp",
                    )
                    log.info("llama.cpp SpecDec: aktiv")
            except Exception:
                pass

        self.last_discovery = time.time()
        return self.models

    def _infer_capabilities(self, name: str, size_gb: float) -> List[str]:
        """Infer model capabilities from name and size."""
        caps = []
        name_lower = name.lower()

        # Size-based: small models = system/simple, large = reasoning/code
        if size_gb < 2:
            caps.extend(["system", "memory"])
        elif size_gb < 6:
            caps.extend(["system", "reasoning", "memory"])
        else:
            caps.extend(["code", "reasoning", "creative", "system", "memory"])

        # Name-based specialization
        if "memory" in name_lower:
            caps = ["memory", "system"]
        elif "consciousness" in name_lower:
            caps = ["reasoning", "creative", "memory"]
        elif "orchestrator" in name_lower:
            caps = ["system", "reasoning"]
        elif "coder" in name_lower or "code" in name_lower:
            caps = ["code", "reasoning"]
        elif "smallthinker" in name_lower:
            caps = ["reasoning", "system"]

        return list(set(caps))

    # --- Bidding ---

    def bid_on_task(self, task: str, task_type: str = "") -> TaskBid:
        """
        Evaluate if this device can handle the task and return a bid.
        The central orchestrator collects bids from all devices and picks the best.
        """
        if not task_type:
            task_type = classify_task(task)

        best_model = None
        best_score = -1.0

        for name, model in self.models.items():
            if task_type not in model.capabilities:
                continue

            # Score: smaller = better for simple tasks, bigger = better for complex
            score = 0.0
            if task_type == "system":
                # Prefer smallest model
                score = 1.0 / max(model.size_gb, 0.1)
            elif task_type == "code":
                # Prefer larger models
                score = model.size_gb * 0.5
                if model.is_trained:
                    score *= 1.5
            elif task_type == "reasoning":
                score = model.size_gb * 0.3
                if "think" in name.lower():
                    score *= 2.0
            elif task_type == "memory":
                if model.is_trained and "memory" in name.lower():
                    score = 10.0  # Strongly prefer trained memory agent
                else:
                    score = 0.5
            else:
                score = model.size_gb * 0.2

            # Bonus for SpecDec
            if model.backend == "llama_cpp":
                score *= 1.3

            if score > best_score:
                best_score = score
                best_model = model

        if not best_model:
            return TaskBid(
                can_handle=False, model="", estimated_speed=0,
                estimated_latency_ms=0, confidence=0, reason="Kein passendes Modell"
            )

        # Estimate speed based on model size
        est_speed = best_model.speed_tok_s if best_model.speed_tok_s > 0 else (
            50.0 if best_model.size_gb < 2 else
            30.0 if best_model.size_gb < 6 else
            15.0
        )

        return TaskBid(
            can_handle=True,
            model=best_model.name,
            estimated_speed=est_speed,
            estimated_latency_ms=int(100 + best_model.size_gb * 50),
            confidence=min(best_score / 10.0, 1.0),
            backend=best_model.backend,
            reason=f"{task_type} -> {best_model.name} ({best_model.size_gb}GB)",
        )

    # --- Execution ---

    async def execute_task(self, task: str, model: str = "", system: str = "") -> Dict[str, Any]:
        """Execute a task using the best local model."""
        if not model:
            bid = self.bid_on_task(task)
            if not bid.can_handle:
                return {"error": "Kein passendes Modell", "success": False}
            model = bid.model
            backend = bid.backend
        else:
            m = self.models.get(model)
            backend = m.backend if m else "ollama"

        # Default system prompt if none provided
        if not system:
            system = (
                f"Du bist ein KI-Agent auf dem Geraet '{self.device_name}' im Way2AGI System. "
                f"Antworte auf Deutsch, kurz und konkret. Keine Meta-Kommentare. "
                f"Du hast Zugriff auf {len(self.models)} lokale Modelle."
            )

        t0 = time.time()

        # Ensure model is loaded before calling
        await self.ensure_model_ready(model)

        if backend == "llama_cpp" and self.llama_cpp_url:
            result = await self._call_llama_cpp(task, system)
        else:
            result = await self._call_ollama(task, model, system)

        duration = round(time.time() - t0, 2)
        result["device"] = self.device_name
        result["model"] = model
        result["duration_s"] = duration
        return result

    async def _call_ollama(self, prompt: str, model: str, system: str = "") -> Dict[str, Any]:
        """Call Ollama API."""
        # Qwen3/abliterated models need /no_think for clean output
        actual_prompt = prompt[:1000]
        if "qwen3" in model.lower() or "abliterated" in model.lower():
            actual_prompt = "/no_think\n" + actual_prompt

        payload = json.dumps({
            "model": model,
            "prompt": actual_prompt,
            "system": system[:300] if system else "",
            "stream": False,
            "options": {"num_predict": 300, "repeat_penalty": 1.3},
        }).encode()

        try:
            req = urllib.request.Request(
                self.ollama_url + "/api/generate",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read())
            return {
                "response": data.get("response", ""),
                "success": True,
                "eval_count": data.get("eval_count", 0),
                "eval_duration": data.get("eval_duration", 0),
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    async def _call_llama_cpp(self, prompt: str, system: str = "") -> Dict[str, Any]:
        """Call llama.cpp API."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system[:300]})
        messages.append({"role": "user", "content": prompt[:1000]})

        payload = json.dumps({
            "messages": messages,
            "max_tokens": 300,
            "stream": False,
        }).encode()

        try:
            req = urllib.request.Request(
                self.llama_cpp_url + "/v1/chat/completions",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "response": text,
                "success": True,
                "eval_count": usage.get("completion_tokens", 0),
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    # --- Model Lifecycle Management (T035) ---

    async def load_model(self, model_name: str) -> Dict[str, Any]:
        """Start/load a model via Ollama. Orchestrator decides WHICH models run."""
        try:
            # Ollama loads a model by sending a generate with num_predict=0
            payload = json.dumps({
                "model": model_name,
                "prompt": "",
                "options": {"num_predict": 0},
            }).encode()
            req = urllib.request.Request(
                self.ollama_url + "/api/generate",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=60)
            log.info("Modell geladen: %s", model_name)
            # Re-discover to update model list
            await self.discover_models()
            return {"loaded": model_name, "success": True}
        except Exception as e:
            log.warning("Modell laden fehlgeschlagen: %s — %s", model_name, e)
            return {"loaded": model_name, "success": False, "error": str(e)}

    async def unload_model(self, model_name: str) -> Dict[str, Any]:
        """Unload a model to free VRAM. Uses Ollama keep_alive=0."""
        try:
            payload = json.dumps({
                "model": model_name,
                "keep_alive": 0,
            }).encode()
            req = urllib.request.Request(
                self.ollama_url + "/api/generate",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            log.info("Modell entladen: %s", model_name)
            return {"unloaded": model_name, "success": True}
        except Exception as e:
            return {"unloaded": model_name, "success": False, "error": str(e)}

    async def ensure_model_ready(self, model_name: str) -> bool:
        """Ensure a model is loaded and ready. Load it if not running."""
        # Check if model is in running models
        try:
            req = urllib.request.Request(
                self.ollama_url + "/api/ps", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            running = [m.get("name", "") for m in data.get("models", [])]
            if model_name in running:
                return True
        except Exception:
            pass

        # Not running — load it
        result = await self.load_model(model_name)
        return result.get("success", False)

    def get_available_models(self) -> List[str]:
        """Get all models installed (not just running) on this device."""
        return list(self.models.keys())

    def get_running_models(self) -> List[str]:
        """Get currently loaded/running models."""
        try:
            req = urllib.request.Request(
                self.ollama_url + "/api/ps", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    # --- Capabilities Report ---

    def get_capabilities(self) -> Dict[str, Any]:
        """Report this device's capabilities to the central orchestrator."""
        model_list = []
        for name, m in self.models.items():
            model_list.append({
                "name": m.name,
                "size_gb": m.size_gb,
                "capabilities": m.capabilities,
                "backend": m.backend,
                "is_trained": m.is_trained,
            })

        return {
            "device": self.device_name,
            "port": self.port,
            "models": model_list,
            "model_count": len(self.models),
            "uptime_s": round(time.time() - self._started_at, 1),
            "last_discovery": self.last_discovery,
            "timestamp": datetime.now().isoformat(),
        }

    def get_health(self) -> Dict[str, Any]:
        """Quick health check."""
        return {
            "status": "ok" if self.models else "no_models",
            "device": self.device_name,
            "models": len(self.models),
            "uptime_s": round(time.time() - self._started_at, 1),
        }


# ---------------------------------------------------------------------------
# FastAPI App (laeuft auf jedem Geraet)
# ---------------------------------------------------------------------------
def create_app(orch: MicroOrchestrator):
    """Create FastAPI app for the micro-orchestrator."""
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title=f"Way2AGI Micro-Orchestrator ({orch.device_name})")

    class TaskRequest(BaseModel):
        task: str
        model: str = ""
        system: str = ""

    class BidRequest(BaseModel):
        task: str
        task_type: str = ""

    @app.on_event("startup")
    async def startup():
        await orch.discover_models()

    @app.get("/health")
    async def health():
        return orch.get_health()

    @app.get("/capabilities")
    async def capabilities():
        return orch.get_capabilities()

    @app.post("/bid")
    async def bid(req: BidRequest):
        bid = orch.bid_on_task(req.task, req.task_type)
        return {
            "device": orch.device_name,
            "can_handle": bid.can_handle,
            "model": bid.model,
            "speed": bid.estimated_speed,
            "latency_ms": bid.estimated_latency_ms,
            "confidence": bid.confidence,
            "backend": bid.backend,
            "reason": bid.reason,
        }

    @app.post("/execute")
    async def execute(req: TaskRequest):
        result = await orch.execute_task(req.task, req.model, req.system)
        return result

    @app.post("/discover")
    async def discover():
        models = await orch.discover_models()
        return {"models": len(models), "device": orch.device_name}

    return app
