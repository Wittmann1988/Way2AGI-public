"""Orchestrator API Client — Kommuniziert mit dem lokalen Way2AGI Orchestrator.

Fallback: Wenn der Orchestrator nicht antwortet, direkt Ollama ansprechen.
"""
from __future__ import annotations

import requests
from typing import Any

try:
    from cli.identity import get_system_prompt
    _has_identity = True
except ImportError:
    _has_identity = False

ORCHESTRATOR_URL = "http://localhost:8150"
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:0.8b"

# Modelle die think:false brauchen (Qwen3-Familie)
THINK_FALSE_MODELS = {"qwen3", "qwen3.5"}


def _needs_think_false(model: str) -> bool:
    """Prueft ob ein Modell think:false braucht."""
    base = model.split(":")[0].lower()
    return any(base.startswith(prefix) for prefix in THINK_FALSE_MODELS)


def chat(message: str, model: str = "auto", timeout: int = 120) -> str:
    """Sende eine Nachricht. Versucht Orchestrator, dann Ollama Fallback."""
    # Versuch 1: Orchestrator /v1/chat (kurzer Timeout)
    # Elias Identity injizieren
    system_prompt = get_system_prompt(model) if _has_identity else ""

    try:
        r = requests.post(
            f"{ORCHESTRATOR_URL}/v1/chat",
            json={"message": message, "model": model, "system": system_prompt},
            timeout=min(timeout, 10),
        )
        r.raise_for_status()
        data = r.json()
        result = data.get("response", data.get("result", ""))
        if result:
            return result
    except Exception:
        pass

    # Fallback: Direkt Ollama
    try:
        use_model = DEFAULT_MODEL if model == "auto" else model
        msgs = []
        if _has_identity:
            msgs.append({"role": "system", "content": get_system_prompt(use_model)})
        msgs.append({"role": "user", "content": message})
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": msgs,
            "stream": False,
            "options": {"num_predict": 512},
        }
        if _needs_think_false(use_model):
            payload["think"] = False

        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", str(data))
    except requests.ConnectionError:
        return "[Weder Orchestrator noch Ollama erreichbar]"
    except requests.Timeout:
        return f"[Timeout nach {timeout}s — Modell wird evtl. geladen]"
    except Exception as e:
        return f"[Fehler: {e}]"


def chat_stream(message: str, model: str = "auto", timeout: int = 120):
    """Streaming-Chat via Ollama. Yield chunks."""
    use_model = DEFAULT_MODEL if model == "auto" else model
    stream_msgs = []
    if _has_identity:
        stream_msgs.append({"role": "system", "content": get_system_prompt(use_model)})
    stream_msgs.append({"role": "user", "content": message})
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": stream_msgs,
        "stream": True,
        "options": {"num_predict": 512},
    }
    if _needs_think_false(use_model):
        payload["think"] = False

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=timeout,
            stream=True,
        )
        r.raise_for_status()
        import json
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    break
    except Exception as e:
        yield f"[Fehler: {e}]"


def get_nodes() -> list[dict[str, Any]]:
    """Hole den Status aller Compute Nodes."""
    try:
        r = requests.get(f"{ORCHESTRATOR_URL}/v1/nodes", timeout=5)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            result = []
            for name, info in data.items():
                if isinstance(info, dict):
                    info["id"] = name
                    result.append(info)
                else:
                    result.append({"id": name, "info": info})
            return result
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_status() -> dict[str, Any]:
    """Hole den Health-Status des Orchestrators."""
    try:
        r = requests.get(f"{ORCHESTRATOR_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}


def orchestrate(task: str, priority: int = 1, model: str | None = None) -> dict[str, Any]:
    """Sende einen Task an den Orchestrator mit optionalem Model-Hint."""
    try:
        payload: dict[str, Any] = {"task": task, "priority": priority}
        if model:
            payload["model"] = model
        r = requests.post(
            f"{ORCHESTRATOR_URL}/v1/orchestrate",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_models() -> list[str]:
    """Hole die lokal verfuegbaren Modelle von Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []
