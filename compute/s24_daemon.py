#!/usr/bin/env python3
"""
Way2AGI S24 Ultra Triage Daemon
================================
Ultra-leichtgewichtiger Daemon fuer Samsung S24 Ultra in Termux.
Nutzt qwen3:1.7b fuer schnelle Triage/Classification Tasks.

Dependencies:
    pip install fastapi uvicorn httpx

Start:
    python3 s24_daemon.py

API: http://YOUR_MOBILE_IP:8200/docs
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging — nur stdout, kein File-Handler (spart IO)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("s24")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DAEMON_PORT = 8200
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:1.7b"
CONTROLLER_URL = "http://YOUR_CONTROLLER_IP:8050"
HEARTBEAT_INTERVAL = 120  # Sekunden — seltener als Desktop
BATTERY_LOW_THRESHOLD = 20  # Prozent
PREFIX_TMP = os.environ.get("PREFIX", "/data/data/com.termux/files/usr") + "/tmp"

# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

def get_battery() -> dict:
    """Liest Battery-Status via termux-battery-status."""
    try:
        out = subprocess.run(
            ["termux-battery-status"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except Exception as e:
        log.warning("Battery-Check fehlgeschlagen: %s", e)
    return {"percentage": -1, "status": "UNKNOWN", "temperature": 0.0}


def is_battery_low() -> bool:
    bat = get_battery()
    pct = bat.get("percentage", -1)
    if pct < 0:
        return False  # Unbekannt = weitermachen
    return pct < BATTERY_LOW_THRESHOLD

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class State:
    def __init__(self):
        self.start_time = time.time()
        self.requests = 0
        self.http: Optional[httpx.AsyncClient] = None
        self._hb_task: Optional[asyncio.Task] = None
        self._shutdown = False

    async def init(self):
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))

    async def close(self):
        self._shutdown = True
        if self._hb_task:
            self._hb_task.cancel()
        if self.http:
            await self.http.aclose()


state = State()

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

async def ollama_generate(prompt: str, system: str = "", max_tokens: int = 512) -> str:
    """Einzelner Generate-Call an lokales Ollama."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }
    if system:
        payload["system"] = system

    resp = await state.http.post(
        f"{OLLAMA_URL}/api/generate", json=payload, timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


async def ollama_alive() -> bool:
    try:
        r = await state.http.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Controller Registration & Heartbeat
# ---------------------------------------------------------------------------

async def register_at_controller() -> bool:
    payload = {
        "name": "s24",
        "url": f"http://YOUR_MOBILE_IP:{DAEMON_PORT}",
        "node_type": "compute",
        "vram": 0,
        "models": [MODEL],
    }
    try:
        r = await state.http.post(
            f"{CONTROLLER_URL}/nodes/register", json=payload, timeout=10.0,
        )
        if r.status_code == 200:
            log.info("Beim Controller registriert")
            return True
        log.warning("Controller-Registrierung: HTTP %d", r.status_code)
    except Exception as e:
        log.warning("Controller nicht erreichbar: %s", e)
    return False


async def heartbeat_loop():
    """Heartbeat alle 120s — Battery-aware."""
    await asyncio.sleep(5)  # Kurz warten nach Start
    await register_at_controller()

    while not state._shutdown:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            bat = get_battery()
            payload = {
                "name": "s24",
                "url": f"http://YOUR_MOBILE_IP:{DAEMON_PORT}",
                "node_type": "compute",
                "vram": 0,
                "models": [MODEL] if not is_battery_low() else [],
            }
            await state.http.post(
                f"{CONTROLLER_URL}/nodes/register", json=payload, timeout=10.0,
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.debug("Heartbeat fehlgeschlagen: %s", e)

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class InferenceRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_tokens: int = 512

class InferenceResponse(BaseModel):
    model: str
    response: str
    duration_ms: int
    battery_pct: int

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Way2AGI S24 Triage", version="1.0.0")


@app.on_event("startup")
async def on_startup():
    log.info("=== S24 Triage Daemon startet ===")
    await state.init()
    state._hb_task = asyncio.create_task(heartbeat_loop())
    log.info("Modell: %s | Port: %d | Heartbeat: %ds", MODEL, DAEMON_PORT, HEARTBEAT_INTERVAL)


@app.on_event("shutdown")
async def on_shutdown():
    log.info("=== Shutdown ===")
    await state.close()


@app.get("/health")
async def health():
    """Health + Battery Status."""
    bat = get_battery()
    ollama_ok = await ollama_alive()
    pct = bat.get("percentage", -1)
    return {
        "status": "healthy" if ollama_ok and pct > BATTERY_LOW_THRESHOLD else "degraded",
        "ollama": ollama_ok,
        "model": MODEL,
        "battery_pct": pct,
        "battery_status": bat.get("status", "UNKNOWN"),
        "battery_temp": bat.get("temperature", 0.0),
        "uptime_s": int(time.time() - state.start_time),
        "requests": state.requests,
        "inference_enabled": not is_battery_low(),
    }


@app.post("/inference", response_model=InferenceResponse)
async def inference(req: InferenceRequest):
    """Inferenz mit qwen3:1.7b — blockiert bei niedrigem Akku."""
    if is_battery_low():
        bat = get_battery()
        raise HTTPException(
            status_code=503,
            detail=f"Akku zu niedrig ({bat.get('percentage', '?')}%). Inferenz deaktiviert.",
        )

    state.requests += 1
    t0 = time.time()

    try:
        text = await ollama_generate(
            prompt=req.prompt,
            system=req.system or "",
            max_tokens=req.max_tokens,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(500, f"Ollama Fehler: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(500, f"Inferenz fehlgeschlagen: {e}")

    dur = int((time.time() - t0) * 1000)
    bat = get_battery()
    return InferenceResponse(
        model=MODEL,
        response=text,
        duration_ms=dur,
        battery_pct=bat.get("percentage", -1),
    )


@app.post("/triage")
async def triage(req: InferenceRequest):
    """Schnelle Triage: Klassifiziert ein Problem."""
    if is_battery_low():
        raise HTTPException(503, "Akku zu niedrig fuer Inferenz.")

    system = (
        "Du bist ein Triage-Agent. Klassifiziere das Problem in GENAU eine Kategorie:\n"
        "- CODE: Programmierfehler, Bugs, Syntax\n"
        "- NETWORK: Netzwerk, SSH, Verbindung, DNS\n"
        "- SYSTEM: OS, Prozesse, Speicher, Disk\n"
        "- CONFIG: Konfiguration, Einstellungen, Pfade\n"
        "- OTHER: Alles andere\n\n"
        "Antworte NUR mit: KATEGORIE | Kurze Begruendung (max 1 Satz)"
    )

    state.requests += 1
    t0 = time.time()
    text = await ollama_generate(prompt=req.prompt, system=system, max_tokens=64)
    dur = int((time.time() - t0) * 1000)
    bat = get_battery()

    return {
        "classification": text.strip(),
        "model": MODEL,
        "duration_ms": dur,
        "battery_pct": bat.get("percentage", -1),
    }


@app.post("/register")
async def register():
    """Manuell beim Controller re-registrieren."""
    ok = await register_at_controller()
    return {"status": "registered" if ok else "failed", "controller": CONTROLLER_URL}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("S24 Ultra Triage Daemon — qwen3:1.7b")
    log.info("Port %d | Controller %s", DAEMON_PORT, CONTROLLER_URL)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=DAEMON_PORT,
        log_level="warning",  # Weniger Log-Spam auf dem Handy
        access_log=False,      # Spart CPU
    )
