# core/node_daemon.py
"""
Way2AGI Universal Node Daemon v2.0
=================================
EINZIGER Daemon fuer ALLE Geraete (Jetson, Desktop, Laptop, S24, Phone...)
100 % depersonalisiert - Nutzt core/config.py
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from core.config import config
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.config import config

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("way2agi-node")

# ====================== APP ======================
app = FastAPI(
    title=f"Way2AGI Node – {config.USER_MODEL_PREFIX}",
    version="2.0.0",
    description="Universal Daemon fuer alle Way2AGI-Nodes"
)

# ====================== GLOBAL STATE ======================
start_time = time.time()
total_requests = 0
jobs_completed = 0
jobs_failed = 0
active_jobs = 0
last_request_time = time.time()
registered_nodes: Dict[str, dict] = {}


# ====================== REQUEST/RESPONSE MODELS ======================
class InferenceRequest(BaseModel):
    prompt: str
    system: str = ""
    model: str = "auto"
    max_tokens: int = 512
    temperature: float = 0.7
    repeat_penalty: float = 1.3
    priority: int = 5


class NodeRegistration(BaseModel):
    name: str
    ip: str
    port: int
    models: list = []
    gpu: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    node: str
    uptime_seconds: float
    vram_free_gb: float
    battery_pct: int
    consciousness_enabled: bool
    budget_used_today: str
    jobs_completed: int
    jobs_failed: int
    nodes_registered: int


class ResourceBudgetResponse(BaseModel):
    max_gpu_hours_per_day: float
    night_mode: str
    max_storage_gb: int
    pause_on_low_power: bool


# ====================== HELPERS ======================
def get_battery() -> Dict[str, Any]:
    """Battery fuer Termux / Mobile devices"""
    try:
        out = subprocess.run(
            ["termux-battery-status"],
            capture_output=True, text=True, timeout=5
        )
        return json.loads(out.stdout) if out.returncode == 0 else {"percentage": 100}
    except Exception:
        return {"percentage": 100}


def get_vram_free_gb() -> float:
    """Echter VRAM (nvidia-smi) oder RAM-Fallback"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            timeout=5,
        )
        return int(out.decode().strip()) / 1024
    except Exception:
        try:
            import psutil
            return psutil.virtual_memory().available / (1024 ** 3)
        except ImportError:
            return 0.0


def get_system_info() -> Dict[str, Any]:
    """Umfassende System-Info (CPU, RAM, GPU, VRAM)"""
    info = {
        "hostname": platform.node(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "gpu": config.gpu_info,
        "consciousness": config.ENABLE_CONSCIOUSNESS,
        "self_observation": config.ENABLE_SELF_OBSERVATION,
    }
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        info["ram_available_gb"] = round(mem.available / (1024**3), 1)
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except ImportError:
        pass
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            timeout=5,
        ).decode().strip()
        parts = out.split(", ")
        info["vram_used_mb"] = int(parts[0])
        info["vram_total_mb"] = int(parts[1])
        info["gpu_util_pct"] = int(parts[2])
    except Exception:
        pass
    return info


async def is_npu_available() -> bool:
    """Phi Silica NPU Check (Windows Laptop)"""
    try:
        import onnxruntime_genai as og  # noqa: F401
        return True
    except ImportError:
        return False


# ====================== OLLAMA INTEGRATION ======================
async def query_ollama(prompt: str, model: str = "auto", system: str = "",
                       max_tokens: int = 512, temperature: float = 0.7,
                       repeat_penalty: float = 1.3) -> str:
    """Query lokales Ollama oder llama.cpp"""
    try:
        import httpx
    except ImportError:
        import aiohttp
        url = "http://localhost:11434/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model, "messages": messages, "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature,
                        "repeat_penalty": repeat_penalty},
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "")
                return f"Ollama error: {resp.status}"

    url = "http://localhost:11434/api/chat"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model, "messages": messages, "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature,
                    "repeat_penalty": repeat_penalty},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("message", {}).get("content", "")
        return f"Ollama error: {resp.status_code}"


# ====================== RESOURCE BUDGET CHECK ======================
async def check_resource_budget() -> bool:
    """Prueft ob aktuell GPU-Stunden / Night-Mode / Battery erlaubt sind"""
    if config.PAUSE_ALL_ON_LOW_POWER and get_battery().get("percentage", 100) < 20:
        log.warning("RESOURCE BUDGET: Akku zu niedrig — Inference pausiert")
        return False
    return True


# ====================== CONSCIOUSNESS REFLECTION LOOP ======================
async def consciousness_reflection_loop():
    """Selbstbeobachtung – laeuft alle REFLECTION_INTERVAL_MINUTES"""
    if not config.ENABLE_CONSCIOUSNESS:
        return
    while True:
        await asyncio.sleep(config.REFLECTION_INTERVAL_MINUTES * 60)
        log.info(f"[Consciousness] Reflection cycle — jobs: {jobs_completed}, "
                 f"failed: {jobs_failed}, uptime: {int(time.time() - start_time)}s")


# ====================== HEARTBEAT LOOP ======================
async def heartbeat_loop():
    """Registriert sich beim Controller (wenn nicht selbst Controller)"""
    if not config.CONTROLLER_IP:
        return
    while True:
        try:
            url = f"http://{config.CONTROLLER_IP}:8050/nodes/register"
            payload = {
                "name": platform.node(),
                "ip": "0.0.0.0",
                "port": int(os.environ.get("DAEMON_PORT", 8050)),
                "models": [],
                "gpu": config.gpu_info,
            }
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        log.info("Heartbeat sent to controller")
            except ImportError:
                import aiohttp
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                    async with s.post(url, json=payload) as resp:
                        if resp.status == 200:
                            log.info("Heartbeat sent to controller")
        except Exception as e:
            log.warning(f"Heartbeat failed: {e}")
        await asyncio.sleep(30)


# ====================== ENDPOINTS ======================
@app.get("/health", response_model=HealthResponse)
async def health():
    bat = get_battery()
    return HealthResponse(
        status="healthy",
        node=platform.node(),
        uptime_seconds=round(time.time() - start_time, 1),
        vram_free_gb=round(get_vram_free_gb(), 2),
        battery_pct=bat.get("percentage", 100),
        consciousness_enabled=config.ENABLE_CONSCIOUSNESS,
        budget_used_today=f"0.0 / {config.MAX_GPU_HOURS_PER_DAY} GPU-h",
        jobs_completed=jobs_completed,
        jobs_failed=jobs_failed,
        nodes_registered=len(registered_nodes),
    )


@app.post("/inference")
async def inference(req: InferenceRequest):
    global total_requests, jobs_completed, jobs_failed, last_request_time

    if not await check_resource_budget():
        raise HTTPException(503, "Resource Budget Limit erreicht oder Akku zu niedrig")

    total_requests += 1
    last_request_time = time.time()

    try:
        result = await query_ollama(
            prompt=req.prompt,
            model=req.model,
            system=req.system,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            repeat_penalty=req.repeat_penalty,
        )
        jobs_completed += 1
        return {
            "status": "ok",
            "model": req.model,
            "response": result,
            "consciousness_active": config.ENABLE_CONSCIOUSNESS,
        }
    except Exception as e:
        jobs_failed += 1
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/resource-budget", response_model=ResourceBudgetResponse)
async def resource_budget():
    return ResourceBudgetResponse(
        max_gpu_hours_per_day=config.MAX_GPU_HOURS_PER_DAY,
        night_mode=f"{config.NIGHT_MODE_START}:00 – {config.NIGHT_MODE_END}:00",
        max_storage_gb=config.MAX_MODEL_STORAGE_GB,
        pause_on_low_power=config.PAUSE_ALL_ON_LOW_POWER,
    )


@app.get("/system")
async def system_info():
    return get_system_info()


@app.get("/nodes")
async def list_nodes():
    return {"nodes": registered_nodes, "count": len(registered_nodes)}


@app.post("/nodes/register")
async def register_node(reg: NodeRegistration):
    registered_nodes[reg.name] = {
        "ip": reg.ip,
        "port": reg.port,
        "models": reg.models,
        "gpu": reg.gpu,
        "registered_at": datetime.now().isoformat(),
    }
    log.info(f"Node registered: {reg.name} ({reg.ip}:{reg.port})")
    return {"status": "registered", "name": reg.name}


# ====================== LIFECYCLE ======================
@app.on_event("startup")
async def startup_event():
    log.info(f"Way2AGI Universal Node gestartet – {config.USER_MODEL_PREFIX}")
    log.info(f"Consciousness: {'AKTIV' if config.ENABLE_CONSCIOUSNESS else 'AUS'}")
    log.info(f"Resource Budget: max {config.MAX_GPU_HOURS_PER_DAY} GPU-h/Tag")
    npu = await is_npu_available()
    if npu:
        log.info("NPU (Phi Silica) verfuegbar!")
    asyncio.create_task(consciousness_reflection_loop())
    asyncio.create_task(heartbeat_loop())


@app.on_event("shutdown")
async def shutdown_event():
    log.info("Node wird heruntergefahren...")


# ====================== MAIN ======================
if __name__ == "__main__":
    port = int(os.getenv("DAEMON_PORT", 8050))
    log.info(f"Starte Daemon auf Port {port}")
    uvicorn.run(
        "core.node_daemon:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
