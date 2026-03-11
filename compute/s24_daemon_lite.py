#!/usr/bin/env python3
"""
Way2AGI S24 Ultra Triage Daemon — Lite Version
================================================
Stdlib-only (kein FastAPI/pydantic) fuer Termux auf S24.
Nutzt http.server + urllib fuer minimale Dependencies.

Start:
    python3 s24_daemon_lite.py

API: http://YOUR_MOBILE_IP:8200/health
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# Logging
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
HEARTBEAT_INTERVAL = 120
BATTERY_LOW_THRESHOLD = 20
START_TIME = time.time()
REQUEST_COUNT = 0

# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

def get_battery() -> dict:
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
    return pct >= 0 and pct < BATTERY_LOW_THRESHOLD

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def ollama_generate(prompt: str, system: str = "", max_tokens: int = 512) -> str:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }
    if system:
        payload["system"] = system

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=data,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read())
        return result.get("response", "")


def ollama_alive() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Controller Heartbeat
# ---------------------------------------------------------------------------

def register_at_controller() -> bool:
    payload = json.dumps({
        "name": "s24",
        "url": f"http://YOUR_MOBILE_IP:{DAEMON_PORT}",
        "node_type": "compute",
        "vram": 0,
        "models": [MODEL],
    }).encode()
    try:
        req = urllib.request.Request(
            f"{CONTROLLER_URL}/nodes/register",
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log.info("Beim Controller registriert")
                return True
    except Exception as e:
        log.warning("Controller nicht erreichbar: %s", e)
    return False


def heartbeat_loop():
    time.sleep(5)
    register_at_controller()
    while True:
        try:
            time.sleep(HEARTBEAT_INTERVAL)
            payload = json.dumps({
                "name": "s24",
                "url": f"http://YOUR_MOBILE_IP:{DAEMON_PORT}",
                "node_type": "compute",
                "vram": 0,
                "models": [MODEL] if not is_battery_low() else [],
            }).encode()
            req = urllib.request.Request(
                f"{CONTROLLER_URL}/nodes/register",
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.debug("Heartbeat fehlgeschlagen: %s", e)

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class S24Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Kein Access-Log

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/health":
            bat = get_battery()
            pct = bat.get("percentage", -1)
            ok = ollama_alive()
            self._send_json({
                "status": "healthy" if ok and pct > BATTERY_LOW_THRESHOLD else "degraded",
                "ollama": ok,
                "model": MODEL,
                "battery_pct": pct,
                "battery_status": bat.get("status", "UNKNOWN"),
                "battery_temp": bat.get("temperature", 0.0),
                "uptime_s": int(time.time() - START_TIME),
                "requests": REQUEST_COUNT,
                "inference_enabled": not is_battery_low(),
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        global REQUEST_COUNT

        if self.path == "/inference":
            if is_battery_low():
                bat = get_battery()
                self._send_json(
                    {"error": f"Akku zu niedrig ({bat.get('percentage', '?')}%)"}, 503
                )
                return

            body = self._read_body()
            REQUEST_COUNT += 1
            t0 = time.time()
            try:
                text = ollama_generate(
                    prompt=body.get("prompt", ""),
                    system=body.get("system", ""),
                    max_tokens=body.get("max_tokens", 512),
                )
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
                return

            dur = int((time.time() - t0) * 1000)
            bat = get_battery()
            self._send_json({
                "model": MODEL,
                "response": text,
                "duration_ms": dur,
                "battery_pct": bat.get("percentage", -1),
            })

        elif self.path == "/triage":
            if is_battery_low():
                self._send_json({"error": "Akku zu niedrig"}, 503)
                return

            body = self._read_body()
            system = (
                "Du bist ein Triage-Agent. Klassifiziere das Problem in GENAU eine Kategorie:\n"
                "- CODE: Programmierfehler, Bugs, Syntax\n"
                "- NETWORK: Netzwerk, SSH, Verbindung, DNS\n"
                "- SYSTEM: OS, Prozesse, Speicher, Disk\n"
                "- CONFIG: Konfiguration, Einstellungen, Pfade\n"
                "- OTHER: Alles andere\n\n"
                "Antworte NUR mit: KATEGORIE | Kurze Begruendung (max 1 Satz)"
            )
            REQUEST_COUNT += 1
            t0 = time.time()
            try:
                text = ollama_generate(
                    prompt=body.get("prompt", ""), system=system, max_tokens=64,
                )
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
                return

            dur = int((time.time() - t0) * 1000)
            bat = get_battery()
            self._send_json({
                "classification": text.strip(),
                "model": MODEL,
                "duration_ms": dur,
                "battery_pct": bat.get("percentage", -1),
            })

        elif self.path == "/register":
            ok = register_at_controller()
            self._send_json({
                "status": "registered" if ok else "failed",
                "controller": CONTROLLER_URL,
            })

        else:
            self._send_json({"error": "not found"}, 404)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("S24 Ultra Triage Daemon (Lite) — %s", MODEL)
    log.info("Port %d | Controller %s", DAEMON_PORT, CONTROLLER_URL)

    # Heartbeat in Background-Thread
    hb = threading.Thread(target=heartbeat_loop, daemon=True)
    hb.start()

    server = HTTPServer(("0.0.0.0", DAEMON_PORT), S24Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutdown.")
        server.server_close()
