#!/usr/bin/env python3
"""
Way2AGI Inference Node Controller Daemon
================================
Zentraler Controller fuer das Way2AGI Compute-Netzwerk.
Laeuft auf dem Inference Node AGX Orin und orchestriert alle Nodes.

Dependencies:
    pip install fastapi uvicorn httpx apscheduler pydantic

Start:
    python3 inference_daemon.py
    # oder: uvicorn inference_daemon:app --host 0.0.0.0 --port 8050

API: http://YOUR_INFERENCE_NODE_IP:8050/docs
"""

import asyncio
import sqlite3
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.environ.get("LOG_PATH", "/tmp/inference_daemon.log"), mode="a"),
    ],
)
log = logging.getLogger("inference-ctrl")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DAEMON_PORT = 8050
HEARTBEAT_INTERVAL = 60  # Sekunden
CIRCUIT_BREAKER_COOLDOWN = 30  # Sekunden
OLLAMA_LOCAL = "http://localhost:11434"
DESKTOP_NODE_URL = "http://YOUR_COMPUTE_NODE_IP:8100"
ACTION_LOG_DB = "/opt/way2agi/memory/memory.db"

# ---------------------------------------------------------------------------
# Node Registry
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    CONTROLLER = "controller"
    COMPUTE = "compute"
    CLOUD = "cloud"


class NodeStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    CIRCUIT_OPEN = "circuit_open"


class NodeInfo(BaseModel):
    url: str
    node_type: NodeType = Field(alias="type")
    vram: int = 0
    models: list[str] = []
    status: NodeStatus = NodeStatus.OFFLINE
    last_heartbeat: Optional[float] = None
    error_count: int = 0
    circuit_open_until: Optional[float] = None

    model_config = {"populate_by_name": True}


# Statische Node-Definitionen — werden beim Start geladen
# 4-fache Redundanz: Desktop, Inference Node, npu-node (Win Laptop), S24
DEFAULT_NODES: dict[str, dict] = {
    "inference-node": {
        "url": OLLAMA_LOCAL,
        "type": "controller",
        "vram": 32000,
        "description": "Inference Node AGX Orin — Controller, Memory, Identity, Always-On",
    },
    "desktop": {
        "url": DESKTOP_NODE_URL,
        "type": "compute",
        "vram": 32000,
        "description": "Desktop RTX 5090 — Heavy Inference, 21 Modelle",
    },
    "npu-node": {
        "url": "http://YOUR_NPU_NODE_IP:8150",
        "type": "compute",
        "vram": 0,
        "description": "ASUS npu-node Win11 — Phi Silica NPU, Light Inference",
    },
    "s24": {
        "url": "http://YOUR_MOBILE_NODE_IP:8200",
        "type": "compute",
        "vram": 0,
        "description": "mobile-node (Android) — qwen3:1.7b, Triage/Classification",
    },
    "cloud-groq": {
        "url": "https://api.groq.com/openai/v1",
        "type": "cloud",
        "vram": 0,
        "description": "Groq Cloud — Kimi-K2, Ultra-Fast, Free Tier",
    },
    "cloud-gemini": {
        "url": "https://generativelanguage.googleapis.com",
        "type": "cloud",
        "vram": 0,
        "description": "Google Gemini — 2.5 Flash, 1M Context, Free Tier",
    },
    "cloud-openai": {
        "url": "https://api.openai.com/v1",
        "type": "cloud",
        "vram": 0,
        "description": "OpenAI — GPT-4o-mini, Paid",
    },
    "cloud-openrouter": {
        "url": "https://openrouter.ai/api/v1",
        "type": "cloud",
        "vram": 0,
        "description": "OpenRouter — Step-Flash, Qwen-Coder, Free/Paid Mix",
    },
}

# Bekannte lokale Modelle auf dem Inference Node
JETSON_MODELS = [
    "way2agi-memory-agent-sft",
    "nemotron-3-nano:30b",
    "olmo-3:32b-think",
    "olmo-3:7b",
    "way2agi-orchestrator",
    "huihui_ai/qwen3-abliterated:8b",
    "qwen3:8b",
    "deepseek-r1:8b",
    "llama3.1:8b",
]

# Capability Routing — welches Modell fuer welchen Task-Typ
# Fallback-Kette: preferred -> secondary -> tertiary -> cloud
CAPABILITY_MAP: dict[str, dict[str, Any]] = {
    # === Tier 1: Ultra-Light (1.5-1.8B) — Routing, Triage, Simple Tasks ===
    "triage": {"model": "mannix/smallthinker-abliterated", "preferred_node": "inference-node", "fallback": ["s24", "desktop"]},
    "classification": {"model": "mannix/smallthinker-abliterated", "preferred_node": "inference-node", "fallback": ["s24", "desktop"]},
    "orchestration": {"model": "mannix/smallthinker-abliterated", "preferred_node": "inference-node", "fallback": ["s24", "desktop"]},
    "network": {"model": "mannix/smallthinker-abliterated", "preferred_node": "inference-node", "fallback": ["s24", "desktop"]},
    "light": {"model": "mannix/smallthinker-abliterated", "preferred_node": "inference-node", "fallback": ["s24", "npu-node"]},
    "memory": {"model": "way2agi-memory-agent-sft", "preferred_node": "inference-node", "fallback": ["desktop"]},
    # === Tier 2: Medium (8B) — Reflexion, General, Quick Tasks ===
    "general": {"model": "huihui_ai/qwen3-abliterated:8b", "preferred_node": "inference-node", "fallback": ["desktop", "cloud-groq"]},
    "quick": {"model": "huihui_ai/qwen3-abliterated:8b", "preferred_node": "inference-node", "fallback": ["desktop", "cloud-groq"]},
    "thinking": {"model": "huihui_ai/qwen3-abliterated:8b", "preferred_node": "inference-node", "fallback": ["desktop"]},
    # === Tier 3: Heavy (14B+) — nur fuer Code, Deep Reasoning, Research ===
    "code": {"model": "qwen3-coder", "preferred_node": "desktop", "fallback": ["inference-node", "cloud-groq"]},
    "reasoning": {"model": "deepseek-r1", "preferred_node": "desktop", "fallback": ["inference-node", "cloud-groq"]},
    "research": {"model": "nemotron-3-nano:30b", "preferred_node": "inference-node", "fallback": ["desktop", "cloud-gemini"]},
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class DaemonState:
    """Globaler Zustand des Daemons."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodeInfo] = {}
        self.jobs: list[dict[str, Any]] = []
        self.cron_log: list[dict[str, Any]] = []
        self.start_time: float = time.time()
        self.http: Optional[httpx.AsyncClient] = None

    async def init(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        # Default Nodes registrieren
        for name, cfg in DEFAULT_NODES.items():
            self.nodes[name] = NodeInfo(
                url=cfg["url"],
                type=cfg["type"],
                vram=cfg["vram"],
                models=JETSON_MODELS if name == "inference-node" else [],
            )
        log.info("State initialisiert mit %d Nodes", len(self.nodes))

    async def shutdown(self) -> None:
        if self.http:
            await self.http.aclose()


state = DaemonState()

# ---------------------------------------------------------------------------
# Health & Heartbeat
# ---------------------------------------------------------------------------

async def check_ollama_health(url: str) -> tuple[bool, list[str]]:
    """Preuft ob eine Ollama-Instanz erreichbar ist und gibt Modelle zurueck."""
    try:
        resp = await state.http.get(f"{url}/api/tags")
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return True, models
        return False, []
    except Exception:
        return False, []


async def check_compute_node_health(url: str) -> tuple[bool, list[str]]:
    """Prueft ob ein Compute-Node (Desktop Daemon) erreichbar ist."""
    try:
        resp = await state.http.get(f"{url}/health")
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            return True, models
        return False, []
    except Exception:
        return False, []


async def check_cloud_health(name: str, url: str) -> bool:
    """Prueft ob ein Cloud-API erreichbar ist (leichtgewichtiger Check)."""
    node = state.nodes.get(name)
    if node and node.circuit_open_until:
        if time.time() < node.circuit_open_until:
            return False
        # Circuit Breaker zuruecksetzen — Probe
        node.circuit_open_until = None
    try:
        # Groq und Gemini haben unterschiedliche Health-Checks
        if "groq" in name:
            resp = await state.http.get(f"{url}/models", headers=_cloud_headers("groq"))
        else:
            # Gemini — einfacher GET
            resp = await state.http.get(url)
        return resp.status_code in (200, 401, 403)  # Auth-Fehler = erreichbar
    except Exception:
        return False


def _cloud_headers(provider: str) -> dict[str, str]:
    """API-Keys aus Umgebungsvariablen laden."""
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        return {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "gemini":
        return {}  # Gemini nutzt Query-Parameter
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        return {"Authorization": f"Bearer {key}"} if key else {}
    return {}


async def heartbeat_all() -> None:
    """Heartbeat fuer alle registrierten Nodes — laeuft alle 60s."""
    log.info("Heartbeat-Zyklus gestartet")
    now = time.time()

    for name, node in state.nodes.items():
        try:
            if node.node_type == NodeType.CONTROLLER:
                alive, models = await check_ollama_health(node.url)
                if alive:
                    node.status = NodeStatus.ONLINE
                    node.models = models
                    node.error_count = 0
                else:
                    node.status = NodeStatus.OFFLINE
                    node.error_count += 1
                    log.warning("Inference Node Ollama offline — versuche Neustart")
                    await try_restart_ollama()

            elif node.node_type == NodeType.COMPUTE:
                alive, models = await check_compute_node_health(node.url)
                if alive:
                    node.status = NodeStatus.ONLINE
                    node.models = models
                    node.error_count = 0
                else:
                    node.status = NodeStatus.OFFLINE
                    node.error_count += 1

            elif node.node_type == NodeType.CLOUD:
                alive = await check_cloud_health(name, node.url)
                if alive:
                    node.status = NodeStatus.ONLINE
                    node.error_count = 0
                else:
                    node.error_count += 1
                    if node.error_count >= 3:
                        node.status = NodeStatus.CIRCUIT_OPEN
                        node.circuit_open_until = now + CIRCUIT_BREAKER_COOLDOWN
                        log.warning(
                            "Circuit Breaker OPEN fuer %s (Cooldown %ds)",
                            name,
                            CIRCUIT_BREAKER_COOLDOWN,
                        )
                    else:
                        node.status = NodeStatus.DEGRADED

            node.last_heartbeat = now

        except Exception as exc:
            log.error("Heartbeat Fehler fuer %s: %s", name, exc)
            node.status = NodeStatus.OFFLINE
            node.error_count += 1

    online = sum(1 for n in state.nodes.values() if n.status == NodeStatus.ONLINE)
    log.info("Heartbeat fertig — %d/%d Nodes online", online, len(state.nodes))


async def try_restart_ollama() -> None:
    """Versucht den lokalen Ollama-Server neu zu starten."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "restart", "ollama",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Ollama Neustart erfolgreich")
        else:
            log.error("Ollama Neustart fehlgeschlagen: %s", stderr.decode())
    except Exception as exc:
        log.error("Ollama Neustart Exception: %s", exc)



# ---------------------------------------------------------------------------
# Action Logger (E022 Fix)
# ---------------------------------------------------------------------------

def log_action(action_type, module="inference_daemon", model_used=None,
               device="inference-node", input_summary=None, output_summary=None,
               duration_ms=None, success=1, error_id=None):
    """Log an action to action_log table for Selbstbeobachtung."""
    try:
        conn = sqlite3.connect(ACTION_LOG_DB)
        conn.execute(
            "INSERT INTO action_log (action_type, module, model_used, device, "
            "input_summary, output_summary, duration_ms, success, error_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (action_type, module, model_used, device,
             (input_summary or "")[:500], (output_summary or "")[:500],
             duration_ms, success, error_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("Action-Log Fehler: %s", e)


# ---------------------------------------------------------------------------
# Job Routing
# ---------------------------------------------------------------------------

class JobRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    capability: Optional[str] = None  # code, reasoning, quick, memory, etc.
    system: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    priority: int = 5  # 1=hoechste, 10=niedrigste
    stream: bool = False


class JobResult(BaseModel):
    job_id: str
    node: str
    model: str
    response: str
    duration_ms: int
    routed_by: str  # Erklaerung warum dieser Node gewaehlt wurde


def pick_node_and_model(req: JobRequest) -> tuple[str, str, str]:
    """
    Routing-Logik: Waehlt Node und Modell fuer einen Job.
    Returns: (node_name, model_name, reason)
    """
    # 1. Explizites Modell angegeben?
    if req.model:
        # Ist es lokal auf Inference Node?
        inference-node = state.nodes.get("inference-node")
        if inference-node and inference-node.status == NodeStatus.ONLINE:
            for m in inference-node.models:
                if req.model in m or m in req.model:
                    return "inference-node", req.model, f"Modell '{req.model}' lokal auf Inference Node verfuegbar"

        # Ist es auf Desktop?
        desktop = state.nodes.get("desktop")
        if desktop and desktop.status == NodeStatus.ONLINE:
            for m in desktop.models:
                if req.model in m or m in req.model:
                    return "desktop", req.model, f"Modell '{req.model}' auf Desktop verfuegbar"

        # Cloud Fallback
        cloud_node = _pick_cloud_fallback()
        if cloud_node:
            return cloud_node, req.model, f"Modell '{req.model}' via Cloud ({cloud_node})"

    # 2. Capability-based Routing
    if req.capability and req.capability in CAPABILITY_MAP:
        cap = CAPABILITY_MAP[req.capability]
        preferred = cap["preferred_node"]
        model = cap["model"]

        pnode = state.nodes.get(preferred)
        if pnode and pnode.status == NodeStatus.ONLINE:
            return preferred, model, f"Capability '{req.capability}' -> {preferred}/{model}"

        # Fallback: anderer Node
        for nname, ninfo in state.nodes.items():
            if ninfo.status == NodeStatus.ONLINE and nname != preferred:
                return nname, model, f"Capability '{req.capability}' Fallback -> {nname}/{model}"

    # 3. Default: Inference Node mit qwen3:8b
    inference-node = state.nodes.get("inference-node")
    if inference-node and inference-node.status == NodeStatus.ONLINE:
        return "inference-node", "qwen3:8b", "Default-Routing -> Inference Node/qwen3:8b"

    # 4. Desktop Fallback
    desktop = state.nodes.get("desktop")
    if desktop and desktop.status == NodeStatus.ONLINE:
        return "desktop", "qwen3:8b", "Inference Node offline -> Desktop Fallback"

    # 5. Cloud Fallback
    cloud = _pick_cloud_fallback()
    if cloud:
        return cloud, "default", "Alle lokalen Nodes offline -> Cloud Fallback"

    raise HTTPException(503, "Kein Node verfuegbar — alle offline")


def _pick_cloud_fallback() -> Optional[str]:
    """Waehlt Cloud-Provider: Groq > Gemini > OpenAI."""
    for name in ("cloud-groq", "cloud-gemini", "cloud-openai"):
        node = state.nodes.get(name)
        if node and node.status in (NodeStatus.ONLINE, NodeStatus.DEGRADED):
            return name
    return None


async def execute_job_on_node(
    node_name: str, model: str, req: JobRequest
) -> tuple[str, int]:
    """Fuehrt einen Job auf dem gegebenen Node aus."""
    node = state.nodes[node_name]
    t0 = time.time()

    if node.node_type == NodeType.CONTROLLER:
        # Lokaler Ollama-Call
        payload = {
            "model": model,
            "prompt": req.prompt,
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.max_tokens,
            },
        }
        if req.system:
            payload["system"] = req.system

        resp = await state.http.post(
            f"{node.url}/api/generate",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")

    elif node.node_type == NodeType.COMPUTE:
        # Desktop Compute Node — eigenes API
        payload = {
            "model": model,
            "prompt": req.prompt,
            "system": req.system,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        resp = await state.http.post(
            f"{node.url}/generate",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", data.get("text", ""))

    elif node.node_type == NodeType.CLOUD:
        text = await _cloud_generate(node_name, node.url, model, req)

    else:
        raise HTTPException(500, f"Unbekannter Node-Typ: {node.node_type}")

    duration_ms = int((time.time() - t0) * 1000)
    return text, duration_ms


async def _cloud_generate(
    name: str, base_url: str, model: str, req: JobRequest
) -> str:
    """Generierung ueber Cloud-API (OpenAI-kompatibel fuer Groq)."""
    messages = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.prompt})

    if "groq" in name:
        headers = _cloud_headers("groq")
        headers["Content-Type"] = "application/json"
        payload = {
            "model": model if model != "default" else "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        resp = await state.http.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    elif "gemini" in name:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        gmodel = model if model != "default" else "gemini-2.0-flash"
        payload = {
            "contents": [{"parts": [{"text": req.prompt}]}],
            "generationConfig": {
                "temperature": req.temperature,
                "maxOutputTokens": req.max_tokens,
            },
        }
        if req.system:
            payload["systemInstruction"] = {"parts": [{"text": req.system}]}
        resp = await state.http.post(
            f"{base_url}/v1beta/models/{gmodel}:generateContent?key={api_key}",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    raise HTTPException(500, f"Cloud-Provider {name} nicht implementiert")


# ---------------------------------------------------------------------------
# Roundtable — Frage an ALLE Modelle
# ---------------------------------------------------------------------------

class RoundtableRequest(BaseModel):
    question: str
    system: Optional[str] = "Du bist ein Experte. Antworte praezise und ehrlich."
    models: Optional[list[str]] = None  # None = alle verfuegbaren
    temperature: float = 0.7
    max_tokens: int = 1024


class RoundtableResponse(BaseModel):
    question: str
    responses: dict[str, dict[str, Any]]  # model -> {response, node, duration_ms}
    total_duration_ms: int
    consensus: Optional[str] = None


async def run_roundtable(req: RoundtableRequest) -> RoundtableResponse:
    """Sendet die Frage an alle verfuegbaren Modelle und sammelt Antworten."""
    t0 = time.time()
    models_to_query = req.models

    if not models_to_query:
        # Alle Modelle sammeln die online sind
        models_to_query = []
        for name, node in state.nodes.items():
            if node.status == NodeStatus.ONLINE:
                if node.node_type in (NodeType.CONTROLLER, NodeType.COMPUTE):
                    models_to_query.extend(node.models)
                elif node.node_type == NodeType.CLOUD:
                    if "groq" in name:
                        models_to_query.append("groq:llama-3.3-70b-versatile")
                    elif "gemini" in name:
                        models_to_query.append("gemini:gemini-2.0-flash")

    # Deduplizieren
    models_to_query = list(dict.fromkeys(models_to_query))

    responses: dict[str, dict[str, Any]] = {}

    async def query_model(model: str) -> None:
        try:
            # Cloud-Modelle speziell behandeln
            if model.startswith("groq:"):
                actual_model = model.split(":", 1)[1]
                node_name = "cloud-groq"
            elif model.startswith("gemini:"):
                actual_model = model.split(":", 1)[1]
                node_name = "cloud-gemini"
            else:
                # Lokales Modell — finde Node
                node_name = None
                for nname, ninfo in state.nodes.items():
                    if ninfo.status == NodeStatus.ONLINE and model in ninfo.models:
                        node_name = nname
                        break
                if not node_name:
                    responses[model] = {"error": "Kein Node fuer dieses Modell"}
                    return
                actual_model = model

            job_req = JobRequest(
                prompt=req.question,
                model=actual_model,
                system=req.system,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
            text, duration = await execute_job_on_node(node_name, actual_model, job_req)
            responses[model] = {
                "response": text,
                "node": node_name,
                "duration_ms": duration,
            }
        except Exception as exc:
            responses[model] = {"error": str(exc)}

    # Alle Modelle parallel abfragen
    tasks = [query_model(m) for m in models_to_query]
    await asyncio.gather(*tasks, return_exceptions=True)

    total_ms = int((time.time() - t0) * 1000)
    return RoundtableResponse(
        question=req.question,
        responses=responses,
        total_duration_ms=total_ms,
    )


# ---------------------------------------------------------------------------
# Cronjob-Engine
# ---------------------------------------------------------------------------

async def cron_morning_research() -> None:
    """08:00 — Research-Scan: Papers und Repos pruefen."""
    log.info("CRON: Morgen-Research gestartet")
    entry = {
        "time": datetime.datetime.now().isoformat(),
        "type": "research",
        "status": "running",
    }

    try:
        # 1. Arxiv-Scan (LLM-Agents, Self-Improvement, Memory)
        job = JobRequest(
            prompt=(
                "Suche nach den neuesten Papers zu: "
                "1) LLM Self-Improvement "
                "2) AI Memory Systems "
                "3) Multi-Agent Orchestration "
                "4) Consciousness in AI "
                "Fasse die Top 3 Ergebnisse je Kategorie zusammen."
            ),
            capability="research",
            system="Du bist ein AI-Research-Assistent. Fasse praezise zusammen.",
            max_tokens=2048,
        )
        node, model, reason = pick_node_and_model(job)
        text, dur = await execute_job_on_node(node, model, job)
        entry["result"] = text[:500]
        entry["status"] = "completed"
        entry["duration_ms"] = dur
        log.info("CRON: Research fertig (%dms)", dur)

    except Exception as exc:
        entry["status"] = "failed"
        entry["error"] = str(exc)
        log.error("CRON: Research fehlgeschlagen: %s", exc)

    state.cron_log.append(entry)


async def cron_midday_reflection() -> None:
    """13:00 — Reflexions-Zyklus: Was lief gut, was schlecht?"""
    log.info("CRON: Mittags-Reflexion gestartet")
    entry = {
        "time": datetime.datetime.now().isoformat(),
        "type": "reflection",
        "status": "running",
    }

    try:
        # Sammle Status aller Nodes
        node_summary = []
        for name, node in state.nodes.items():
            node_summary.append(
                f"- {name}: {node.status.value}, Fehler: {node.error_count}, "
                f"Modelle: {len(node.models)}"
            )
        nodes_text = "\n".join(node_summary)

        recent_jobs = state.jobs[-20:] if state.jobs else []
        jobs_summary = f"{len(state.jobs)} Jobs total, letzte 20 analysiert"
        failed = sum(1 for j in recent_jobs if j.get("status") == "failed")

        prompt = (
            f"Reflexions-Zyklus fuer Way2AGI Controller.\n\n"
            f"Node-Status:\n{nodes_text}\n\n"
            f"Jobs: {jobs_summary}, davon {failed} fehlgeschlagen.\n\n"
            f"Cron-Log Eintraege: {len(state.cron_log)}\n\n"
            f"Analysiere:\n"
            f"1. Was laeuft gut?\n"
            f"2. Was sind Probleme?\n"
            f"3. Welche Optimierungen sind moeglich?\n"
            f"4. Prioritaeten fuer die naechsten Stunden?"
        )

        job = JobRequest(
            prompt=prompt,
            capability="thinking",
            system="Du bist ein AI-Systemadministrator. Reflektiere ehrlich und praezise.",
            max_tokens=1024,
        )
        node, model, reason = pick_node_and_model(job)
        text, dur = await execute_job_on_node(node, model, job)
        entry["result"] = text[:500]
        entry["status"] = "completed"
        entry["duration_ms"] = dur
        log.info("CRON: Reflexion fertig (%dms)", dur)

    except Exception as exc:
        entry["status"] = "failed"
        entry["error"] = str(exc)
        log.error("CRON: Reflexion fehlgeschlagen: %s", exc)

    state.cron_log.append(entry)


async def cron_evening_export() -> None:
    """20:00 — Training-Daten Export + GoalGuard Check."""
    log.info("CRON: Abend-Export gestartet")
    entry = {
        "time": datetime.datetime.now().isoformat(),
        "type": "export",
        "status": "running",
    }

    try:
        # 1. Training-Daten aus Jobs sammeln
        export_data = []
        for job in state.jobs:
            if job.get("status") == "completed":
                export_data.append({
                    "prompt": job.get("prompt", "")[:200],
                    "model": job.get("model", ""),
                    "node": job.get("node", ""),
                    "duration_ms": job.get("duration_ms", 0),
                    "timestamp": job.get("timestamp", ""),
                })

        export_path = "/tmp/way2agi_training_export.jsonl"
        with open(export_path, "a") as f:
            for item in export_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # 2. GoalGuard Check — pruefe ob Ziele eingehalten werden
        job = JobRequest(
            prompt=(
                "GoalGuard Check:\n"
                f"- Jobs heute: {len(state.jobs)}\n"
                f"- Nodes online: {sum(1 for n in state.nodes.values() if n.status == NodeStatus.ONLINE)}\n"
                f"- Cron-Tasks: {len(state.cron_log)}\n\n"
                "Pruefe: Sind alle Way2AGI-Ziele auf Kurs? "
                "Gibt es kritische Blocker? "
                "Was muss morgen als erstes passieren?"
            ),
            capability="memory",
            system="Du bist GoalGuard — der Waechter der Way2AGI-Ziele.",
            max_tokens=512,
        )
        node, model, reason = pick_node_and_model(job)
        text, dur = await execute_job_on_node(node, model, job)

        entry["exported_items"] = len(export_data)
        entry["export_path"] = export_path
        entry["goalguard"] = text[:300]
        entry["status"] = "completed"
        entry["duration_ms"] = dur
        log.info("CRON: Export fertig — %d Items, GoalGuard OK (%dms)", len(export_data), dur)

    except Exception as exc:
        entry["status"] = "failed"
        entry["error"] = str(exc)
        log.error("CRON: Export fehlgeschlagen: %s", exc)

    state.cron_log.append(entry)


async def cron_watchdog() -> None:
    """Alle 10 Minuten: Prueft ob alle Nodes ihre Aufgaben erfuellen.

    - Sind alle Nodes erreichbar?
    - Laufen die Cronjobs auf allen Nodes?
    - Falls ein Node ausfaellt, uebernimmt dieser Controller dessen Aufgaben.
    - Prueft TODOs und arbeitet die hoechste Prioritaet ab.
    """
    log.info("WATCHDOG: Pruefe System-Gesundheit")
    issues = []

    # 1. Node-Health pruefen
    for name, node in state.nodes.items():
        if node.status == NodeStatus.OFFLINE and name != "npu-node":  # npu-node IP noch unbekannt
            issues.append(f"Node '{name}' ist OFFLINE")
            # Versuche Neustart wenn lokal
            if name == "inference-node":
                await try_restart_ollama()

    # 2. Cronjob-Ausfuehrung pruefen
    now = datetime.datetime.now()
    today_crons = [
        e for e in state.cron_log
        if e.get("time", "").startswith(now.strftime("%Y-%m-%d"))
    ]

    # Pruefen ob erwartete Crons gelaufen sind
    expected_crons = []
    if now.hour >= 8:
        expected_crons.append("research")
    if now.hour >= 13:
        expected_crons.append("reflection")
    if now.hour >= 20:
        expected_crons.append("export")

    for cron_type in expected_crons:
        ran = any(e.get("type") == cron_type for e in today_crons)
        if not ran:
            issues.append(f"Cronjob '{cron_type}' hat heute noch nicht gelaufen — starte jetzt")
            # Nachholen
            if cron_type == "research":
                await cron_morning_research()
            elif cron_type == "reflection":
                await cron_midday_reflection()
            elif cron_type == "export":
                await cron_evening_export()

    # 3. Broadcast Health an alle Nodes
    for name, node in state.nodes.items():
        if node.status == NodeStatus.ONLINE and node.node_type == NodeType.COMPUTE:
            try:
                await state.http.post(
                    f"{node.url}/health-report",
                    json={
                        "controller": "inference-node",
                        "issues": issues,
                        "nodes_online": sum(
                            1 for n in state.nodes.values()
                            if n.status == NodeStatus.ONLINE
                        ),
                        "timestamp": now.isoformat(),
                    },
                    timeout=5.0,
                )
            except Exception:
                pass  # Node mag das Endpoint nicht haben — okay

    if issues:
        log.warning("WATCHDOG: %d Issues gefunden: %s", len(issues), "; ".join(issues))
    else:
        log.info("WATCHDOG: Alles OK — %d Nodes online, Crons aktuell",
                 sum(1 for n in state.nodes.values() if n.status == NodeStatus.ONLINE))


# ---------------------------------------------------------------------------
# Pydantic Models fuer API
# ---------------------------------------------------------------------------

class NodeRegisterRequest(BaseModel):
    name: str
    url: str
    node_type: str = "compute"
    vram: int = 0
    models: list[str] = []


class ReflectRequest(BaseModel):
    focus: Optional[str] = None  # Optionaler Fokus fuer Reflexion


class ScheduleEntry(BaseModel):
    time: str
    name: str
    description: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup und Shutdown des Daemons."""
    log.info("=== Way2AGI Inference Node Controller startet ===")
    await state.init()

    # Initialer Heartbeat
    await heartbeat_all()

    # Scheduler konfigurieren
    scheduler.add_job(heartbeat_all, "interval", seconds=HEARTBEAT_INTERVAL, id="heartbeat")
    scheduler.add_job(cron_morning_research, "cron", hour=8, minute=0, id="morning_research")
    scheduler.add_job(cron_midday_reflection, "cron", hour=13, minute=0, id="midday_reflection")
    scheduler.add_job(cron_evening_export, "cron", hour=20, minute=0, id="evening_export")
    scheduler.add_job(cron_watchdog, "interval", minutes=10, id="watchdog")
    scheduler.start()

    log.info("Scheduler gestartet — Heartbeat alle %ds, 3 Cronjobs aktiv", HEARTBEAT_INTERVAL)
    log.info("=== Controller bereit auf Port %d ===", DAEMON_PORT)

    yield

    log.info("=== Shutdown ===")
    scheduler.shutdown(wait=False)
    await state.shutdown()


app = FastAPI(
    title="Way2AGI Inference Node Controller",
    description="Zentraler Controller fuer das Way2AGI Compute-Netzwerk",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Endpoints ---

@app.get("/health")
async def health():
    """Gesamtstatus des Controllers und aller Nodes."""
    online = sum(1 for n in state.nodes.values() if n.status == NodeStatus.ONLINE)
    total = len(state.nodes)
    uptime_s = int(time.time() - state.start_time)

    return {
        "status": "healthy" if online > 0 else "degraded",
        "uptime_seconds": uptime_s,
        "nodes_online": online,
        "nodes_total": total,
        "jobs_processed": len(state.jobs),
        "cron_tasks_run": len(state.cron_log),
        "version": "1.0.0",
    }


@app.get("/nodes")
async def list_nodes():
    """Alle registrierten Nodes und deren Status."""
    result = {}
    for name, node in state.nodes.items():
        result[name] = {
            "url": node.url,
            "type": node.node_type.value,
            "status": node.status.value,
            "vram": node.vram,
            "models": node.models,
            "model_count": len(node.models),
            "error_count": node.error_count,
            "last_heartbeat": (
                datetime.datetime.fromtimestamp(node.last_heartbeat).isoformat()
                if node.last_heartbeat
                else None
            ),
        }
    return result


@app.post("/nodes/register")
async def register_node(req: NodeRegisterRequest):
    """Node registriert sich beim Controller."""
    state.nodes[req.name] = NodeInfo(
        url=req.url,
        type=req.node_type,
        vram=req.vram,
        models=req.models,
        status=NodeStatus.ONLINE,
        last_heartbeat=time.time(),
    )
    log.info(
        "Node registriert: %s (%s) — %d Modelle, %d MB VRAM",
        req.name, req.url, len(req.models), req.vram,
    )
    return {
        "status": "registered",
        "node": req.name,
        "controller": f"http://YOUR_INFERENCE_NODE_IP:{DAEMON_PORT}",
    }


@app.post("/job")
async def submit_job(req: JobRequest):
    """Neuen Job einreichen — wird automatisch geroutet."""
    job_id = str(uuid.uuid4())[:8]
    log.info("Job %s: prompt=%s... capability=%s", job_id, req.prompt[:50], req.capability)

    node_name, model, reason = pick_node_and_model(req)
    log.info("Job %s geroutet -> %s/%s (%s)", job_id, node_name, model, reason)

    try:
        text, duration_ms = await execute_job_on_node(node_name, model, req)

        job_record = {
            "job_id": job_id,
            "prompt": req.prompt[:200],
            "model": model,
            "node": node_name,
            "status": "completed",
            "duration_ms": duration_ms,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        state.jobs.append(job_record)

        log_action("inference", model_used=model, device=node_name,
                   input_summary=req.prompt[:200], output_summary=text[:200],
                   duration_ms=duration_ms, success=1)

        return JobResult(
            job_id=job_id,
            node=node_name,
            model=model,
            response=text,
            duration_ms=duration_ms,
            routed_by=reason,
        )

    except Exception as exc:
        job_record = {
            "job_id": job_id,
            "prompt": req.prompt[:200],
            "model": model,
            "node": node_name,
            "status": "failed",
            "error": str(exc),
            "timestamp": datetime.datetime.now().isoformat(),
        }
        state.jobs.append(job_record)
        log_action("inference", model_used=model, device=node_name,
                   input_summary=req.prompt[:200], output_summary=str(exc)[:200],
                   duration_ms=0, success=0)
        log.error("Job %s fehlgeschlagen: %s", job_id, exc)
        raise HTTPException(500, f"Job fehlgeschlagen auf {node_name}: {exc}")


@app.post("/roundtable")
async def roundtable(req: RoundtableRequest):
    """Frage an ALLE verfuegbaren Modelle senden und Antworten sammeln."""
    log.info("Roundtable: %s...", req.question[:60])
    result = await run_roundtable(req)
    log.info(
        "Roundtable fertig — %d Antworten in %dms",
        len(result.responses),
        result.total_duration_ms,
    )
    log_action("roundtable", input_summary=req.question[:200],
               output_summary="%d Antworten" % len(result.responses),
               duration_ms=result.total_duration_ms, success=1)
    return result


@app.get("/schedule")
async def get_schedule():
    """Aktuelle Cronjob-Schedule und letzte Ausfuehrungen."""
    jobs_info = []
    for job in scheduler.get_jobs():
        jobs_info.append(
            ScheduleEntry(
                time=str(job.trigger),
                name=job.id,
                description={
                    "heartbeat": "Heartbeat aller Nodes",
                    "morning_research": "Research-Scan (Papers + Repos)",
                    "midday_reflection": "Reflexions-Zyklus",
                    "evening_export": "Training-Daten Export + GoalGuard",
                }.get(job.id, job.id),
                next_run=str(job.next_run_time) if job.next_run_time else None,
            )
        )

    recent_cron = state.cron_log[-10:] if state.cron_log else []
    return {
        "scheduled_jobs": [j.model_dump() for j in jobs_info],
        "recent_executions": recent_cron,
    }


@app.post("/reflect")
async def reflect(req: ReflectRequest):
    """Reflexions-Zyklus manuell triggern."""
    log.info("Manuelle Reflexion gestartet (Fokus: %s)", req.focus or "allgemein")

    focus_text = ""
    if req.focus:
        focus_text = f"\nBesonderer Fokus: {req.focus}\n"

    node_summary = []
    for name, node in state.nodes.items():
        node_summary.append(
            f"- {name}: {node.status.value}, Fehler: {node.error_count}, "
            f"Modelle: {len(node.models)}"
        )
    nodes_text = "\n".join(node_summary)

    job = JobRequest(
        prompt=(
            f"Manuelle Reflexion fuer Way2AGI Controller.{focus_text}\n\n"
            f"Node-Status:\n{nodes_text}\n\n"
            f"Jobs total: {len(state.jobs)}\n"
            f"Cron-Eintraege: {len(state.cron_log)}\n"
            f"Uptime: {int(time.time() - state.start_time)}s\n\n"
            f"Reflektiere:\n"
            f"1. Systemgesundheit\n"
            f"2. Routing-Effizienz\n"
            f"3. Verbesserungsvorschlaege\n"
            f"4. Naechste Schritte"
        ),
        capability="general",
        system="Du bist Elias — die selbstreflektierende KI hinter Way2AGI. Reflektiere ehrlich. /no_think",
        max_tokens=1024,
    )

    try:
        node_name, model, reason = pick_node_and_model(job)
        text, dur = await execute_job_on_node(node_name, model, job)
        return {
            "status": "completed",
            "reflection": text,
            "node": node_name,
            "model": model,
            "duration_ms": dur,
            "focus": req.focus,
        }
    except Exception as exc:
        log.error("Reflexion fehlgeschlagen: %s", exc)
        raise HTTPException(500, f"Reflexion fehlgeschlagen: {exc}")




# ---------------------------------------------------------------------------
# Composer Integration (E023 Fix)
# ---------------------------------------------------------------------------

class ComposeRequest(BaseModel):
    task: str
    strategy: str = "chain"  # chain | parallel | moa
    models: Optional[list[str]] = None  # Optionale Model-Liste
    system: Optional[str] = None
    max_tokens: int = 2048


@app.post("/compose")
async def compose_task(req: ComposeRequest):
    """Multi-Model Task-Komposition via Composer."""
    log.info("Compose: strategy=%s, task=%s...", req.strategy, req.task[:60])
    t0 = time.time()

    try:
        # Sammle verfuegbare Online-Nodes und deren Modelle
        available = {}
        for name, node in state.nodes.items():
            if node.status == NodeStatus.ONLINE and node.models:
                available[name] = node.models

        if not available:
            raise HTTPException(503, "Keine Nodes online fuer Composition")

        # Schritt 1: Task-Zerlegung via lfm2 (oder bestes verfuegbares Modell)
        decompose_prompt = (
            "Zerlege diese Aufgabe in 2-4 Sub-Tasks. "
            "Fuer jeden Sub-Task: beschreibe ihn kurz und nenne die benoetigte Faehigkeit "
            "(code/reasoning/summarize/analyze/general).\n\n"
            "Aufgabe: %s\n\n"
            "Antworte als JSON-Array: "
            '[{"id": "s1", "description": "...", "skill": "...", "depends_on": []}]'
        ) % req.task

        decompose_req = JobRequest(
            prompt=decompose_prompt,
            capability="reasoning",
            system="Du bist ein Task-Decomposer. Antworte NUR mit validem JSON. /no_think",
            max_tokens=1024,
        )
        node_name, model, reason = pick_node_and_model(decompose_req)
        decompose_text, _ = await execute_job_on_node(node_name, model, decompose_req)

        # Parse Sub-Tasks
        import re as _re
        json_match = _re.search(r'\[.*\]', decompose_text, _re.DOTALL)
        if json_match:
            subtasks_raw = json.loads(json_match.group())
        else:
            # Fallback: ganzen Task als einen Sub-Task behandeln
            subtasks_raw = [{"id": "s1", "description": req.task, "skill": "general", "depends_on": []}]

        # Schritt 2: Sub-Tasks ausfuehren
        results = []
        context = ""

        if req.strategy == "chain":
            for st in subtasks_raw:
                sub_prompt = st["description"]
                if context:
                    sub_prompt = "Kontext aus vorherigem Schritt:\n%s\n\nAufgabe: %s" % (context[:1000], sub_prompt)

                sub_req = JobRequest(
                    prompt=sub_prompt,
                    capability=st.get("skill", "general"),
                    system=req.system or "Du bist ein spezialisierter Agent. /no_think",
                    max_tokens=req.max_tokens,
                )
                sn, sm, sr = pick_node_and_model(sub_req)
                text, dur = await execute_job_on_node(sn, sm, sub_req)
                results.append({
                    "subtask_id": st["id"],
                    "description": st["description"],
                    "model": sm,
                    "node": sn,
                    "response": text,
                    "duration_ms": dur,
                })
                context = text

        elif req.strategy == "parallel":
            async def run_subtask(st):
                sub_req = JobRequest(
                    prompt=st["description"],
                    capability=st.get("skill", "general"),
                    system=req.system or "Du bist ein spezialisierter Agent. /no_think",
                    max_tokens=req.max_tokens,
                )
                sn, sm, sr = pick_node_and_model(sub_req)
                text, dur = await execute_job_on_node(sn, sm, sub_req)
                return {
                    "subtask_id": st["id"],
                    "description": st["description"],
                    "model": sm,
                    "node": sn,
                    "response": text,
                    "duration_ms": dur,
                }

            results = await asyncio.gather(*[run_subtask(st) for st in subtasks_raw])
            results = list(results)

        elif req.strategy == "moa":
            # Mixture of Agents: alle Modelle beantworten, dann Synthese
            async def ask_model(node_name, model_name):
                sub_req = JobRequest(
                    prompt=req.task,
                    model=model_name,
                    system=req.system or "Beantworte die Aufgabe so gut du kannst. /no_think",
                    max_tokens=req.max_tokens,
                )
                text, dur = await execute_job_on_node(node_name, model_name, sub_req)
                return {"model": model_name, "node": node_name, "response": text, "duration_ms": dur}

            # Frage alle verfuegbaren Modelle
            tasks = []
            seen_models = set()
            for nname, models in available.items():
                for m in models[:2]:  # Max 2 Modelle pro Node
                    if m not in seen_models:
                        seen_models.add(m)
                        tasks.append(ask_model(nname, m))
                    if len(tasks) >= 5:
                        break
                if len(tasks) >= 5:
                    break

            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            valid = [r for r in raw_results if isinstance(r, dict)]

            # Synthese
            synthesis_prompt = "Hier sind %d Antworten verschiedener Modelle auf die Frage: %s\n\n" % (len(valid), req.task)
            for i, r in enumerate(valid):
                synthesis_prompt += "--- Modell %s ---\n%s\n\n" % (r["model"], r["response"][:500])
            synthesis_prompt += "Erstelle eine Synthese: Was ist der Konsens? Wo gibt es Abweichungen?"

            synth_req = JobRequest(prompt=synthesis_prompt, capability="reasoning", max_tokens=req.max_tokens)
            sn, sm, sr = pick_node_and_model(synth_req)
            synth_text, synth_dur = await execute_job_on_node(sn, sm, synth_req)

            results = valid
            results.append({"subtask_id": "synthesis", "model": sm, "node": sn, "response": synth_text, "duration_ms": synth_dur})

        total_ms = int((time.time() - t0) * 1000)
        log_action("compose", model_used=req.strategy,
                   input_summary=req.task[:200],
                   output_summary="%d Schritte in %dms" % (len(results), total_ms),
                   duration_ms=total_ms, success=1)

        return {
            "strategy": req.strategy,
            "subtask_count": len(results),
            "results": results,
            "total_duration_ms": total_ms,
        }

    except HTTPException:
        raise
    except Exception as exc:
        total_ms = int((time.time() - t0) * 1000)
        log_action("compose", input_summary=req.task[:200],
                   output_summary=str(exc)[:200], duration_ms=total_ms, success=0)
        log.error("Compose fehlgeschlagen: %s", exc)
        raise HTTPException(500, "Compose fehlgeschlagen: %s" % exc)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    log.info("Starte Way2AGI Inference Node Controller Daemon auf Port %d", DAEMON_PORT)
    uvicorn.run(
        "inference_daemon:app",
        host="0.0.0.0",
        port=DAEMON_PORT,
        log_level="info",
        access_log=True,
    )
