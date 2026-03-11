# core/node_daemon.py — One daemon for ALL devices
import asyncio
import os
import time
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from core.config import config
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.config import config

log = logging.getLogger("way2agi-node")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title=f"Way2AGI Node — {config.USER_MODEL_PREFIX}")

# === State ===
NODE_START = time.time()
jobs_completed = 0
jobs_failed = 0
registered_nodes = {}


# === Models ===
class JobRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    max_tokens: int = 512
    temperature: float = 0.7
    repeat_penalty: float = 1.3
    system: Optional[str] = None


class NodeRegistration(BaseModel):
    name: str
    ip: str
    port: int
    models: list = []
    gpu: Optional[str] = None


# === System Info ===
def get_system_info():
    info = {
        "hostname": os.uname().nodename,
        "platform": os.uname().sysname,
        "machine": os.uname().machine,
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
        import subprocess
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


# === Ollama Integration ===
async def query_ollama(prompt: str, model: str = "nemotron", system: str = None,
                       max_tokens: int = 512, temperature: float = 0.7,
                       repeat_penalty: float = 1.3):
    import aiohttp
    url = "http://localhost:11434/api/chat"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
            "repeat_penalty": repeat_penalty,
        },
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "")
                else:
                    return f"Ollama error: {resp.status}"
    except Exception as e:
        return f"Ollama connection failed: {e}"


# === Endpoints ===
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "uptime_s": int(time.time() - NODE_START),
        "node": os.uname().nodename,
        "jobs_completed": jobs_completed,
        "jobs_failed": jobs_failed,
        "nodes_registered": len(registered_nodes),
        "resource_budget": f"{config.MAX_GPU_HOURS_PER_DAY} GPU-h/day",
        "consciousness": config.ENABLE_CONSCIOUSNESS,
        **get_system_info(),
    }


@app.post("/job")
async def run_job(req: JobRequest):
    global jobs_completed, jobs_failed
    try:
        result = await query_ollama(
            prompt=req.prompt,
            model=req.model or "nemotron",
            system=req.system,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            repeat_penalty=req.repeat_penalty,
        )
        jobs_completed += 1
        return {"status": "ok", "result": result, "model": req.model}
    except Exception as e:
        jobs_failed += 1
        raise HTTPException(status_code=500, detail=str(e))


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


@app.get("/system")
async def system_info():
    return get_system_info()


# === Background Tasks ===
async def heartbeat_loop():
    """Register with controller if we're not the controller."""
    if not config.CONTROLLER_IP:
        return
    import aiohttp
    while True:
        try:
            url = f"http://{config.CONTROLLER_IP}:8050/nodes/register"
            payload = {
                "name": os.uname().nodename,
                "ip": "0.0.0.0",
                "port": int(os.environ.get("PORT", 8050)),
                "models": [],
                "gpu": config.gpu_info,
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.post(url, json=payload) as resp:
                    if resp.status == 200:
                        log.info("Heartbeat sent to controller")
        except Exception as e:
            log.warning(f"Heartbeat failed: {e}")
        await asyncio.sleep(30)


async def reflection_loop():
    """Consciousness self-observation cycle."""
    if not config.ENABLE_CONSCIOUSNESS:
        return
    while True:
        await asyncio.sleep(config.REFLECTION_INTERVAL_MINUTES * 60)
        log.info(f"[Consciousness] Reflection cycle — jobs: {jobs_completed}, "
                 f"failed: {jobs_failed}, uptime: {int(time.time() - NODE_START)}s")


@app.on_event("startup")
async def startup():
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(reflection_loop())
    log.info(f"Way2AGI Node started on {os.uname().nodename} — "
             f"GPU: {config.gpu_info}, Consciousness: {config.ENABLE_CONSCIOUSNESS}")


# === Main ===
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8050))
    uvicorn.run(app, host="0.0.0.0", port=port)
