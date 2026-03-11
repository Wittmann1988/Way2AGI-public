"""
Way2AGI Orchestration Server
=============================
Das zentrale Gehirn — empfaengt Tasks, routet zu Modellen, koordiniert Agents.

Laeuft auf Zenbook (YOUR_LAPTOP_IP:8150).
Start: uvicorn orchestrator.src.server:app --host 0.0.0.0 --port 8150
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Optional imports — graceful degradation if modules don't exist yet
# ---------------------------------------------------------------------------
try:
    from .smart_router import SmartRouter
    _has_smart_router = True
except ImportError:
    SmartRouter = None  # type: ignore[assignment,misc]
    _has_smart_router = False

try:
    from .cloud_providers import CloudProviderManager
    _has_cloud_providers = True
except ImportError:
    CloudProviderManager = None  # type: ignore[assignment,misc]
    _has_cloud_providers = False

try:
    from .composer import ModelComposer
    _has_composer = True
except ImportError:
    ModelComposer = None  # type: ignore[assignment,misc]
    _has_composer = False

try:
    from .registry import CapabilityRegistry, build_default_registry
    _has_registry = True
except ImportError:
    CapabilityRegistry = None  # type: ignore[assignment,misc]
    build_default_registry = None  # type: ignore[assignment]
    _has_registry = False

try:
    from .system_prompts import get_prompt
except ImportError:
    def get_prompt(role: str, extra_context: str = "") -> str:  # type: ignore[misc]
        return f"Du bist ein Agent im Way2AGI System. Rolle: {role}"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("way2agi.server")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("ELIAS_DB", "/data/way2agi/memory/memory.db")

NODES: dict[str, dict[str, Any]] = {
    "jetson": {
        "ip": "YOUR_CONTROLLER_IP",
        "ollama": "http://YOUR_CONTROLLER_IP:11434",
        "llama_cpp": "http://YOUR_CONTROLLER_IP:8080",
        "role": "Controller, Memory, Always-On",
        "models": ["nemotron-3-nano:30b", "lfm2:24b", "qwen3-abliterated:8b"],
    },
    "desktop": {
        "ip": "YOUR_DESKTOP_IP",
        "ollama": "http://YOUR_DESKTOP_IP:11434",
        "llama_cpp": "http://YOUR_DESKTOP_IP:8080",
        "role": "Heavy Compute, Training (WoL)",
        "models": ["lfm2:24b", "step-3.5-flash", "qwen3.5:9b", "deepseek-r1:7b"],
    },
    "zenbook": {
        "ip": "YOUR_LAPTOP_IP",
        "ollama": "http://YOUR_LAPTOP_IP:11434",
        "llama_cpp": "http://YOUR_LAPTOP_IP:8080",
        "role": "Orchestrierung, Agents",
        "models": ["smallthinker:1.8b"],
    },
    "s24": {
        "ip": "YOUR_MOBILE_IP",
        "ollama": "http://YOUR_MOBILE_IP:11434",
        "llama_cpp": None,
        "role": "Lite, Verifikation",
        "models": ["qwen3:1.7b"],
    },
}

# Runtime state
node_status: dict[str, dict[str, Any]] = {}
active_tasks: dict[str, dict[str, Any]] = {}
ws_clients: list[WebSocket] = []
cost_tracker: dict[str, float] = {"total_usd": 0.0, "session_usd": 0.0}
_startup_time: float = 0.0


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class OrchestrateRequest(BaseModel):
    task: str
    priority: int = 50
    strategy: str = "auto"  # auto | chain | parallel | moa


class OrchestrateResponse(BaseModel):
    result: Any
    routing: dict[str, Any]
    duration_s: float
    traces: list[dict[str, Any]] = []


class ChatRequest(BaseModel):
    message: str
    model: str = "auto"  # auto | nemotron | lfm2 | cloud
    system: str = ""


class ChatResponse(BaseModel):
    response: str
    model_used: str
    node: str
    duration_s: float


class TaskSubmit(BaseModel):
    title: str
    description: str = ""
    priority: int = 50


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"


class StatusResponse(BaseModel):
    nodes: dict[str, Any]
    active_tasks: int
    models_available: dict[str, list[str]]
    memory_stats: dict[str, Any]
    cost: dict[str, float]
    uptime_s: float


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    """Return a new SQLite connection (thread-safe: one per call)."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def db_memory_stats() -> dict[str, Any]:
    """Grab quick memory stats."""
    try:
        db = get_db()
        stats: dict[str, Any] = {}
        for table in ("memories", "entities", "relations", "todos", "traces", "errors"):
            try:
                row = db.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
                stats[table] = row["c"] if row else 0
            except sqlite3.OperationalError:
                stats[table] = -1
        db.close()
        return stats
    except Exception as e:
        log.warning("Memory stats fehlgeschlagen: %s", e)
        return {"error": str(e)}


def save_action_log(
    action_type: str,
    module: str,
    model_used: str = "",
    device: str = "",
    input_summary: str = "",
    output_summary: str = "",
    success: bool = True,
) -> None:
    """Write to action_log in the background (fire-and-forget)."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO action_log (action_type, module, model_used, device, "
            "input_summary, output_summary, success) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_type, module, model_used, device,
             input_summary[:500], (output_summary or "")[:500], 1 if success else 0),
        )
        db.commit()
        db.close()
    except Exception as e:
        log.debug("action_log schreiben fehlgeschlagen: %s", e)


def save_trace(
    operation: str,
    input_data: str,
    output_data: str,
    duration_ms: int,
    success: bool,
    model: str = "",
) -> None:
    """Write to traces table."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO traces (timestamp, operation, input_data, output_data, "
            "duration_ms, success, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), operation, input_data[:2000], output_data[:2000],
             duration_ms, 1 if success else 0, model),
        )
        db.commit()
        db.close()
    except Exception as e:
        log.debug("trace schreiben fehlgeschlagen: %s", e)


# ---------------------------------------------------------------------------
# Model calling — simple urllib, same pattern as agent_loop.py
# ---------------------------------------------------------------------------
def call_llama_cpp(endpoint: str, messages: list[dict], model: str = "",
                   max_tokens: int = 2048, timeout: int = 120) -> dict[str, Any]:
    """Call a llama.cpp /v1/chat/completions endpoint. Returns raw JSON."""
    url = endpoint.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def call_ollama(endpoint: str, prompt: str, model: str,
                system: str = "", timeout: int = 120) -> dict[str, Any]:
    """Call an Ollama /api/generate endpoint. Returns raw JSON."""
    url = endpoint.rstrip("/") + "/api/generate"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 2048},
    }
    if system:
        payload["system"] = system
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def call_model_simple(
    prompt: str,
    model: str = "auto",
    system: str = "",
    timeout: int = 120,
) -> tuple[str, str, str]:
    """
    High-level model call. Tries llama.cpp first, then Ollama, across all
    available nodes. Returns (response_text, model_used, node_name).
    """
    # Model -> node mapping
    model_map: dict[str, tuple[str, str]] = {
        "nemotron": ("jetson", "nemotron-3-nano:30b"),
        "lfm2": ("jetson", "lfm2:24b"),
        "qwen3-abl": ("jetson", "huihui_ai/qwen3-abliterated:8b"),
        "qwen3.5": ("desktop", "qwen3.5:9b"),
        "deepseek-r1": ("desktop", "deepseek-r1:7b"),
        "smallthinker": ("zenbook", "smallthinker:1.8b"),
        "qwen3-lite": ("s24", "qwen3:1.7b"),
    }

    # Resolve "auto" — pick the best available node
    if model == "auto" or model == "cloud":
        # Priority: jetson nemotron > desktop qwen3.5 > zenbook smallthinker
        preferred = ["nemotron", "lfm2", "qwen3.5", "smallthinker", "qwen3-lite"]
    else:
        # Check if it's a known alias
        preferred = [model] if model in model_map else ["nemotron", "lfm2"]

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for alias in preferred:
        if alias not in model_map:
            continue
        node_name, ollama_model = model_map[alias]
        node_cfg = NODES.get(node_name, {})

        # Check if node is known to be down
        ns = node_status.get(node_name, {})
        if ns.get("status") == "down":
            continue

        # Try llama.cpp first
        llama_ep = node_cfg.get("llama_cpp")
        if llama_ep:
            try:
                result = call_llama_cpp(llama_ep, messages, model=ollama_model,
                                        timeout=timeout)
                text = result["choices"][0]["message"]["content"]
                log.info("llama.cpp %s (%s): OK", node_name, ollama_model)
                return text, ollama_model, node_name
            except Exception as e:
                log.debug("llama.cpp %s fehlgeschlagen: %s", node_name, e)

        # Try Ollama
        ollama_ep = node_cfg.get("ollama")
        if ollama_ep:
            try:
                result = call_ollama(ollama_ep, prompt, model=ollama_model,
                                     system=system, timeout=timeout)
                text = result.get("response", "")
                log.info("Ollama %s (%s): OK", node_name, ollama_model)
                return text, ollama_model, node_name
            except Exception as e:
                log.debug("Ollama %s fehlgeschlagen: %s", node_name, e)

    raise RuntimeError("Kein Modell-Endpoint erreichbar")


# ---------------------------------------------------------------------------
# Task classification (lightweight, runs locally)
# ---------------------------------------------------------------------------
TASK_CATEGORIES = {
    "code": ["code", "programm", "script", "funktion", "bug", "fix", "python", "typescript",
             "implement", "refactor", "debug", "api"],
    "reasoning": ["warum", "erklaer", "analysier", "vergleich", "bewert", "denk",
                  "reason", "think", "math", "logik", "plan"],
    "creative": ["schreib", "text", "story", "gedicht", "zusammenfass", "formulier",
                 "write", "creative", "prompt"],
    "memory": ["erinner", "speicher", "memory", "wann", "letzte", "frueher", "history"],
    "system": ["status", "node", "health", "restart", "deploy", "update", "config"],
}


def classify_task(task: str) -> str:
    """Simple keyword-based task classification."""
    task_lower = task.lower()
    scores: dict[str, int] = {}
    for category, keywords in TASK_CATEGORIES.items():
        scores[category] = sum(1 for kw in keywords if kw in task_lower)
    if not any(scores.values()):
        return "reasoning"
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def pick_strategy(task_type: str, explicit: str) -> str:
    """Choose composition strategy."""
    if explicit != "auto":
        return explicit
    # Simple heuristic
    strategy_map = {
        "code": "chain",
        "reasoning": "chain",
        "creative": "moa",
        "memory": "chain",
        "system": "chain",
    }
    return strategy_map.get(task_type, "chain")


def route_task(task_type: str) -> tuple[str, str]:
    """Pick node + model based on task type. Returns (node_name, model_alias)."""
    routing = {
        "code": ("desktop", "qwen3.5"),
        "reasoning": ("jetson", "nemotron"),
        "creative": ("jetson", "lfm2"),
        "memory": ("jetson", "nemotron"),
        "system": ("zenbook", "smallthinker"),
    }
    node, model = routing.get(task_type, ("jetson", "nemotron"))
    # Fallback if preferred node is down
    ns = node_status.get(node, {})
    if ns.get("status") == "down":
        # Try jetson first, then any available
        for fallback in ["jetson", "desktop", "zenbook", "s24"]:
            if fallback != node and node_status.get(fallback, {}).get("status") != "down":
                log.info("Routing-Fallback: %s -> %s", node, fallback)
                return fallback, model
    return node, model


# ---------------------------------------------------------------------------
# Node health checking
# ---------------------------------------------------------------------------
def check_node_health(node_name: str) -> dict[str, Any]:
    """Check a single node's health. Returns status dict."""
    cfg = NODES[node_name]
    result: dict[str, Any] = {
        "name": node_name,
        "ip": cfg["ip"],
        "status": "down",
        "latency_ms": -1,
        "models_loaded": [],
        "last_seen": datetime.now().isoformat(),
        "active_requests": 0,
        "backends": {},
    }

    # Check llama.cpp /health
    llama_ep = cfg.get("llama_cpp")
    if llama_ep:
        try:
            t0 = time.time()
            req = urllib.request.Request(llama_ep + "/health", method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            latency = int((time.time() - t0) * 1000)
            data = json.loads(resp.read())
            result["backends"]["llama_cpp"] = "up"
            result["status"] = "up"
            result["latency_ms"] = latency
            # slots_idle / slots_processing if available
            if "slots_idle" in data:
                result["active_requests"] = data.get("slots_processing", 0)
        except Exception:
            result["backends"]["llama_cpp"] = "down"

    # Check Ollama /api/tags
    ollama_ep = cfg.get("ollama")
    if ollama_ep:
        try:
            t0 = time.time()
            req = urllib.request.Request(ollama_ep + "/api/tags", method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            latency = int((time.time() - t0) * 1000)
            data = json.loads(resp.read())
            result["backends"]["ollama"] = "up"
            if result["status"] != "up":
                result["status"] = "up"
                result["latency_ms"] = latency
            # Extract loaded model names
            models = [m.get("name", "") for m in data.get("models", [])]
            result["models_loaded"] = models
        except Exception:
            result["backends"]["ollama"] = "down"

    return result


async def poll_node_health() -> None:
    """Background task: poll all nodes every 30s."""
    while True:
        for name in NODES:
            try:
                status = await asyncio.get_event_loop().run_in_executor(
                    None, check_node_health, name
                )
                old_status = node_status.get(name, {}).get("status")
                node_status[name] = status

                # Broadcast status change via WebSocket
                if old_status and old_status != status["status"]:
                    await broadcast_ws({
                        "type": "node_status",
                        "node": name,
                        "status": status["status"],
                        "timestamp": datetime.now().isoformat(),
                    })
                    log.info("Node %s: %s -> %s", name, old_status, status["status"])
            except Exception as e:
                log.warning("Health-Check %s fehlgeschlagen: %s", name, e)
                node_status[name] = {
                    "name": name, "ip": NODES[name]["ip"],
                    "status": "down", "latency_ms": -1,
                    "last_seen": datetime.now().isoformat(),
                    "backends": {}, "models_loaded": [],
                }

        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------
async def broadcast_ws(data: dict[str, Any]) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    dead: list[WebSocket] = []
    msg = json.dumps(data, default=str)
    for ws in ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# Agent loop background runner
# ---------------------------------------------------------------------------
async def run_agent_task(task_id: str) -> None:
    """Run the agent loop for a task in the background."""
    try:
        from .agent_loop import AgentLoop

        ollama_eps = {n: cfg["ollama"] for n, cfg in NODES.items() if cfg.get("ollama")}
        llama_eps = {n: cfg["llama_cpp"] for n, cfg in NODES.items() if cfg.get("llama_cpp")}

        agent = AgentLoop(ollama_endpoints=ollama_eps, llama_cpp_endpoints=llama_eps)

        # Run blocking call in executor
        result = await asyncio.get_event_loop().run_in_executor(
            None, agent.run_task, task_id
        )

        # Update active_tasks
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = result.get("status", "done")
            active_tasks[task_id]["result"] = result

        await broadcast_ws({
            "type": "task_complete",
            "task_id": task_id,
            "status": result.get("status"),
            "timestamp": datetime.now().isoformat(),
        })
    except ImportError:
        log.warning("agent_loop nicht verfuegbar — Task %s kann nicht gestartet werden", task_id)
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = "error"
            active_tasks[task_id]["error"] = "agent_loop Modul nicht verfuegbar"
    except Exception as e:
        log.error("Agent-Loop fuer %s fehlgeschlagen: %s", task_id, e)
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = "error"
            active_tasks[task_id]["error"] = str(e)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_time
    _startup_time = time.time()

    # Banner
    log.info("=" * 60)
    log.info("  Way2AGI Orchestration Server")
    log.info("  Port: 8150 | DB: %s", DB_PATH)
    log.info("  SmartRouter: %s | Composer: %s | Registry: %s",
             "ja" if _has_smart_router else "nein",
             "ja" if _has_composer else "nein",
             "ja" if _has_registry else "nein")
    log.info("=" * 60)

    # Initial health check
    log.info("Initiale Node-Checks...")
    for name in NODES:
        try:
            status = check_node_health(name)
            node_status[name] = status
            log.info("  %s: %s (latency %dms, models: %s)",
                     name, status["status"], status["latency_ms"],
                     ", ".join(status.get("models_loaded", [])[:3]) or "—")
        except Exception as e:
            log.warning("  %s: FEHLER — %s", name, e)
            node_status[name] = {"name": name, "ip": NODES[name]["ip"],
                                 "status": "down", "latency_ms": -1,
                                 "backends": {}, "models_loaded": []}

    # Memory DB check
    if Path(DB_PATH).exists():
        stats = db_memory_stats()
        log.info("Memory DB: %s", json.dumps(stats))
    else:
        log.warning("Memory DB nicht gefunden: %s", DB_PATH)

    log.info("=" * 60)

    # Start background polling
    health_task = asyncio.create_task(poll_node_health())

    yield

    # Shutdown
    health_task.cancel()
    log.info("Server heruntergefahren.")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Way2AGI Orchestrator",
    version="1.0.0",
    description="Zentraler Orchestrierungsserver fuer das Way2AGI System",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for dashboard (mount only if directory exists)
_dashboard_dir = Path(__file__).parent.parent.parent / "dashboard"
if _dashboard_dir.is_dir():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "uptime_s": round(time.time() - _startup_time, 1),
    }


@app.get("/v1/status", response_model=StatusResponse)
async def get_status():
    models_available: dict[str, list[str]] = {}
    for name, ns in node_status.items():
        if ns.get("status") == "up":
            models_available[name] = ns.get("models_loaded", NODES[name].get("models", []))

    return StatusResponse(
        nodes=node_status,
        active_tasks=len([t for t in active_tasks.values() if t.get("status") == "running"]),
        models_available=models_available,
        memory_stats=db_memory_stats(),
        cost=cost_tracker,
        uptime_s=round(time.time() - _startup_time, 1),
    )


@app.get("/v1/nodes")
async def get_nodes():
    nodes_detail = {}
    for name, cfg in NODES.items():
        ns = node_status.get(name, {})
        nodes_detail[name] = {
            "ip": cfg["ip"],
            "role": cfg["role"],
            "status": ns.get("status", "unknown"),
            "backends": ns.get("backends", {}),
            "models_configured": cfg.get("models", []),
            "models_loaded": ns.get("models_loaded", []),
            "latency_ms": ns.get("latency_ms", -1),
            "active_requests": ns.get("active_requests", 0),
            "last_seen": ns.get("last_seen", "never"),
        }
    return nodes_detail


@app.post("/v1/orchestrate", response_model=OrchestrateResponse)
async def orchestrate(req: OrchestrateRequest):
    t0 = time.time()
    traces: list[dict[str, Any]] = []

    # 1. Classify task
    task_type = classify_task(req.task)
    traces.append({"step": "classify", "result": task_type})

    # 2. Pick strategy
    strategy = pick_strategy(task_type, req.strategy)
    traces.append({"step": "strategy", "result": strategy})

    # 3. Route to node/model
    target_node, model_alias = route_task(task_type)
    traces.append({"step": "route", "node": target_node, "model": model_alias})

    # 4. Execute
    system_prompt = get_prompt("orchestrator")
    try:
        response_text, model_used, actual_node = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: call_model_simple(req.task, model=model_alias, system=system_prompt),
        )
        traces.append({"step": "execute", "status": "ok", "model": model_used, "node": actual_node})
    except Exception as e:
        log.error("Orchestrate fehlgeschlagen: %s", e)
        duration = round(time.time() - t0, 2)
        save_action_log("orchestrate", "server", input_summary=req.task[:200],
                        output_summary=str(e), success=False)
        return OrchestrateResponse(
            result=f"Fehler: {e}",
            routing={"node": target_node, "model": model_alias, "strategy": strategy},
            duration_s=duration,
            traces=traces,
        )

    duration = round(time.time() - t0, 2)

    # 5. Save to memory
    save_action_log(
        "orchestrate", "server", model_used=model_used, device=actual_node,
        input_summary=req.task[:200], output_summary=response_text[:300],
    )
    save_trace(
        "orchestrate", req.task[:2000], response_text[:2000],
        int(duration * 1000), True, model_used,
    )

    # Broadcast to WS
    await broadcast_ws({
        "type": "orchestrate_complete",
        "task_preview": req.task[:80],
        "node": actual_node,
        "duration_s": duration,
        "timestamp": datetime.now().isoformat(),
    })

    return OrchestrateResponse(
        result=response_text,
        routing={"node": actual_node, "model": model_used, "strategy": strategy},
        duration_s=duration,
        traces=traces,
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    t0 = time.time()
    system = req.system or get_prompt("orchestrator", "Direkte Chat-Interaktion.")

    try:
        response_text, model_used, node_name = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: call_model_simple(req.message, model=req.model, system=system),
        )
    except Exception as e:
        log.error("Chat fehlgeschlagen: %s", e)
        return ChatResponse(
            response=f"Fehler: {e}",
            model_used="none",
            node="none",
            duration_s=round(time.time() - t0, 2),
        )

    duration = round(time.time() - t0, 2)

    save_trace(
        "chat", req.message[:2000], response_text[:2000],
        int(duration * 1000), True, model_used,
    )

    return ChatResponse(
        response=response_text,
        model_used=model_used,
        node=node_name,
        duration_s=duration,
    )


@app.post("/v1/task", response_model=TaskSubmitResponse)
async def submit_task(req: TaskSubmit):
    task_id = f"T{int(time.time()) % 10000:04d}"

    # Insert into todos table
    try:
        db = get_db()
        db.execute(
            "INSERT INTO todos (id, title, description, priority, status, created_at) "
            "VALUES (?, ?, ?, ?, 'open', datetime('now'))",
            (task_id, req.title, req.description, req.priority),
        )
        db.commit()
        db.close()
    except Exception as e:
        log.warning("TODO in DB schreiben fehlgeschlagen (evtl. Schema): %s", e)

    # Track and start background agent
    active_tasks[task_id] = {
        "id": task_id,
        "title": req.title,
        "status": "running",
        "started_at": datetime.now().isoformat(),
    }

    asyncio.create_task(run_agent_task(task_id))

    await broadcast_ws({
        "type": "task_submitted",
        "task_id": task_id,
        "title": req.title,
        "timestamp": datetime.now().isoformat(),
    })

    return TaskSubmitResponse(task_id=task_id, status="queued")


@app.get("/v1/tasks")
async def list_tasks():
    # Combine DB tasks + in-memory active tasks
    tasks: list[dict[str, Any]] = []

    try:
        db = get_db()
        rows = db.execute(
            "SELECT id, title, description, priority, status, created_at, completed_at "
            "FROM todos ORDER BY priority DESC, created_at DESC LIMIT 100"
        ).fetchall()
        for row in rows:
            tasks.append(dict(row))
        db.close()
    except Exception as e:
        log.warning("TODOs aus DB laden fehlgeschlagen: %s", e)

    # Merge active task info
    for task_id, info in active_tasks.items():
        found = False
        for t in tasks:
            if t.get("id") == task_id:
                t["runtime_status"] = info.get("status")
                found = True
                break
        if not found:
            tasks.append(info)

    return {"tasks": tasks, "count": len(tasks)}


@app.get("/v1/memory/search")
async def memory_search(q: str = Query(..., min_length=1)):
    """Search memories by content (simple LIKE query)."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT id, content, type, importance, namespace, created_at "
            "FROM memories WHERE content LIKE ? ORDER BY importance DESC LIMIT 20",
            (f"%{q}%",),
        ).fetchall()
        db.close()
        return {"query": q, "results": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        log.warning("Memory-Suche fehlgeschlagen: %s", e)
        return {"query": q, "results": [], "count": 0, "error": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    log.info("WebSocket Client verbunden (%d aktiv)", len(ws_clients))

    try:
        # Send initial state
        await ws.send_text(json.dumps({
            "type": "init",
            "nodes": node_status,
            "active_tasks": len(active_tasks),
            "timestamp": datetime.now().isoformat(),
        }, default=str))

        # Keep alive and receive messages
        while True:
            data = await ws.receive_text()
            # Handle ping
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("WebSocket Fehler: %s", e)
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)
        log.info("WebSocket Client getrennt (%d aktiv)", len(ws_clients))


# ---------------------------------------------------------------------------
# Main (direct execution)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "orchestrator.src.server:app",
        host="0.0.0.0",
        port=8150,
        log_level="info",
    )
