# agents/base_agent.py
"""
Way2AGI Base Agent — Gemeinsame Schnittstelle fuer alle Agenten.
================================================================

Stellt sicher dass alle Agenten:
- Experience-Sharing unterstuetzen (GEA)
- An den Knowledge-Graph angebunden sind
- Einheitlich mit dem Orchestrator kommunizieren

Usage:
    from agents.base_agent import BaseAgent
    class MyAgent(BaseAgent):
        def execute(self, task): ...
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.base_agent")

DB_PATH = os.environ.get("WAY2AGI_DB", "/data/elias-memory/memory.db")


@dataclass
class AgentTrace:
    """Trace einer Agent-Ausfuehrung — fuer GEA Experience-Sharing."""
    agent_id: str
    task: str
    approach: str
    outcome: str
    score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """
    Basis-Klasse fuer alle Way2AGI Agenten.

    Jeder Agent kann:
    - Tasks ausfuehren (execute)
    - Erfahrungen von anderen Agenten empfangen (update_from_shared)
    - Traces erzeugen fuer GEA Evolution
    """

    def __init__(self, agent_id: str, db_path: str = DB_PATH) -> None:
        self.agent_id = agent_id
        self.db_path = db_path
        self.shared_state: Dict[str, Any] = {}
        self._traces: List[AgentTrace] = []

    def execute(self, task: str) -> str:
        """Fuehre einen Task aus. Muss von Subklassen implementiert werden."""
        raise NotImplementedError("Subklasse muss execute() implementieren")

    def update_from_shared(self, traces: List[Dict[str, Any]]) -> None:
        """
        Aktualisiere Agent-Zustand aus geteilten Erfahrungen (GEA).
        Wird von GroupEvolvingAgent aufgerufen.
        """
        for trace in traces:
            score = trace.get("score", 0)
            if score >= 0.7:
                # Gute Erfahrung: als Strategie-Template uebernehmen
                self.shared_state.setdefault("good_strategies", []).append({
                    "approach": trace.get("approach", ""),
                    "task": trace.get("task", ""),
                    "score": score,
                })
            elif score < 0.3:
                # Schlechte Erfahrung: als Warnung merken
                self.shared_state.setdefault("warnings", []).append({
                    "approach": trace.get("approach", ""),
                    "reason": trace.get("outcome", ""),
                })

        # Begrenze gespeicherte Strategien
        for key in ("good_strategies", "warnings"):
            if key in self.shared_state:
                self.shared_state[key] = self.shared_state[key][-20:]

        log.info("Agent %s: updated from %d shared traces", self.agent_id, len(traces))

    def record_trace(self, task: str, approach: str, outcome: str, score: float) -> AgentTrace:
        """Zeichne eine Ausfuehrungs-Trace auf."""
        trace = AgentTrace(
            agent_id=self.agent_id,
            task=task,
            approach=approach,
            outcome=outcome,
            score=score,
        )
        self._traces.append(trace)

        # Persistiere in DB
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO action_log (action, context, result, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (f"agent_trace:{self.agent_id}",
                     json.dumps({"task": task, "approach": approach}),
                     json.dumps({"outcome": outcome, "score": score}),
                     trace.timestamp),
                )
        except Exception as e:
            log.debug("Trace persist failed (non-critical): %s", e)

        return trace

    def get_traces(self, limit: int = 10) -> List[AgentTrace]:
        """Gib die letzten Traces zurueck."""
        return self._traces[-limit:]

    def get_shared_strategies(self) -> List[Dict[str, Any]]:
        """Gib gelernte Strategien zurueck."""
        return self.shared_state.get("good_strategies", [])
