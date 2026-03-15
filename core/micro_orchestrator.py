# core/micro_orchestrator.py
"""
MicroOrchestrator — Leichtgewichtige Task-Verteilung.
=====================================================

Wrapper um den vollen Orchestrator fuer einfache Aufrufe.
Nutzt smart_router + composer intern, bietet einfache API.

Usage:
    from core.micro_orchestrator import MicroOrchestrator
    orch = MicroOrchestrator()
    result = orch.route_and_execute("Analysiere diesen Code")
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.micro_orchestrator")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8150")

# Fallback Ollama endpoints (direkt, wenn Orchestrator nicht laeuft)
OLLAMA_ENDPOINTS = [
    ("http://192.168.50.21:11434", "huihui_ai/qwen3-abliterated:8b"),
    ("http://192.168.50.129:11434", "qwen3.5:9b"),
    ("http://localhost:11434", "huihui_ai/qwen3-abliterated:8b"),
]


class MicroOrchestrator:
    """
    Leichtgewichtiger Orchestrator fuer direkte Nutzung.

    Versucht:
    1. Orchestrator-Server (falls laeuft)
    2. Direkten Ollama-Aufruf als Fallback
    """

    def __init__(self, orchestrator_url: str = ORCHESTRATOR_URL) -> None:
        self.orchestrator_url = orchestrator_url

    def route_and_execute(self, prompt: str, system: str = "", timeout: int = 60) -> str:
        """Route Task zum besten verfuegbaren Modell und fuehre aus."""
        # Versuch 1: Orchestrator-Server
        result = self._try_orchestrator(prompt, system, timeout)
        if result:
            return result

        # Versuch 2: Direkter Ollama-Aufruf
        return self._try_ollama_direct(prompt, system, timeout)

    def decompose_task(self, task: str, timeout: int = 60) -> List[Dict[str, Any]]:
        """Zerlege Task in Sub-Tasks via LLM."""
        prompt = (
            f"Zerlege diesen Task in 2-5 ausfuehrbare Schritte:\n\n{task}\n\n"
            "Format (JSON-Array):\n"
            '[{"id": "step1", "task": "...", "agent": "reasoner"}, '
            '{"id": "step2", "task": "...", "agent": "researcher"}]'
        )
        response = self.route_and_execute(prompt, timeout=timeout)

        # Parse JSON
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                pass

        return [{"id": "step1", "task": task, "agent": "reasoner"}]

    def _try_orchestrator(self, prompt: str, system: str, timeout: int) -> Optional[str]:
        """Versuche den Orchestrator-Server."""
        try:
            payload = json.dumps({
                "prompt": prompt,
                "system": system,
            }).encode()
            req = urllib.request.Request(
                f"{self.orchestrator_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                return data.get("response", "")
        except Exception as e:
            log.debug("Orchestrator unavailable: %s", e)
            return None

    def _try_ollama_direct(self, prompt: str, system: str, timeout: int) -> str:
        """Direkter Ollama-Aufruf als Fallback."""
        for endpoint, model in OLLAMA_ENDPOINTS:
            try:
                payload = json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 512},
                }).encode()
                req = urllib.request.Request(
                    f"{endpoint}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                    return data.get("response", "")
            except Exception as e:
                log.debug("Ollama %s failed: %s", endpoint, e)
                continue

        return "[FEHLER: Kein LLM-Endpoint erreichbar]"
