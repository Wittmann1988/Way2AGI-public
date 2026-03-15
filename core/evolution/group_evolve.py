"""
Group-Evolving Agents (GEA) — Self-Evolving Engine fuer Way2AGI.
================================================================

Basiert auf GEA + RoboPhD Papers (arXiv Feb/Maerz 2026):
- Agenten teilen Experience via Knowledge-Graph (bereits in Memory)
- Closed-loop: Plan -> Execute -> Observe -> Evolve -> Share
- Ziel: 71% SWE-Bench-Score durch kollektive Evolution

Integration:
- Nutzt memory/ fuer persistenten Knowledge-Graph
- Nutzt orchestrator/ fuer Task-Routing
- Nutzt agents/consciousness_agent fuer Selbstbeobachtung

Usage:
    from core.evolution.group_evolve import GroupEvolvingEngine
    engine = GroupEvolvingEngine(db_path="/data/elias-memory/memory.db")
    await engine.evolve_cycle(task="Implementiere Feature X")
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("way2agi.group_evolve")


# ---------------------------------------------------------------------------
# Evolution Phases
# ---------------------------------------------------------------------------

class EvolutionPhase(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    OBSERVE = "observe"
    EVOLVE = "evolve"
    SHARE = "share"


@dataclass
class Experience:
    """Eine einzelne Erfahrung eines Agenten."""
    agent_id: str
    task: str
    approach: str
    outcome: str
    score: float  # 0.0 - 1.0
    lessons: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EvolutionState:
    """Zustand der Evolution eines Agenten."""
    agent_id: str
    generation: int = 0
    total_experiences: int = 0
    avg_score: float = 0.0
    best_strategies: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Knowledge Graph (SQLite-backed)
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """Persistenter Knowledge-Graph fuer Experience-Sharing."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS gea_experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        task TEXT NOT NULL,
        approach TEXT NOT NULL,
        outcome TEXT NOT NULL,
        score REAL NOT NULL,
        lessons TEXT DEFAULT '[]',
        generation INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS gea_evolution_state (
        agent_id TEXT PRIMARY KEY,
        generation INTEGER DEFAULT 0,
        total_experiences INTEGER DEFAULT 0,
        avg_score REAL DEFAULT 0.0,
        best_strategies TEXT DEFAULT '[]',
        weaknesses TEXT DEFAULT '[]',
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS gea_shared_knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_agent TEXT NOT NULL,
        knowledge_type TEXT NOT NULL,
        content TEXT NOT NULL,
        relevance_score REAL DEFAULT 0.5,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_gea_exp_agent ON gea_experiences(agent_id);
    CREATE INDEX IF NOT EXISTS idx_gea_exp_score ON gea_experiences(score DESC);
    CREATE INDEX IF NOT EXISTS idx_gea_shared_type ON gea_shared_knowledge(knowledge_type);
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    def store_experience(self, exp: Experience, generation: int = 0) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO gea_experiences (agent_id, task, approach, outcome, score, lessons, generation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (exp.agent_id, exp.task, exp.approach, exp.outcome, exp.score,
                 json.dumps(exp.lessons), generation),
            )

    def get_best_experiences(self, limit: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM gea_experiences ORDER BY score DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_agent_experiences(self, agent_id: str, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM gea_experiences WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_evolution_state(self, state: EvolutionState) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO gea_evolution_state "
                "(agent_id, generation, total_experiences, avg_score, best_strategies, weaknesses, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (state.agent_id, state.generation, state.total_experiences,
                 state.avg_score, json.dumps(state.best_strategies),
                 json.dumps(state.weaknesses)),
            )

    def get_evolution_state(self, agent_id: str) -> Optional[EvolutionState]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM gea_evolution_state WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if not row:
                return None
            return EvolutionState(
                agent_id=row["agent_id"],
                generation=row["generation"],
                total_experiences=row["total_experiences"],
                avg_score=row["avg_score"],
                best_strategies=json.loads(row["best_strategies"]),
                weaknesses=json.loads(row["weaknesses"]),
            )

    def share_knowledge(self, source: str, ktype: str, content: str, relevance: float = 0.5) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO gea_shared_knowledge (source_agent, knowledge_type, content, relevance_score) "
                "VALUES (?, ?, ?, ?)",
                (source, ktype, content, relevance),
            )

    def get_shared_knowledge(self, ktype: Optional[str] = None, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if ktype:
                rows = conn.execute(
                    "SELECT * FROM gea_shared_knowledge WHERE knowledge_type = ? "
                    "ORDER BY relevance_score DESC LIMIT ?", (ktype, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gea_shared_knowledge ORDER BY relevance_score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# LLM Helper
# ---------------------------------------------------------------------------

OLLAMA_ENDPOINTS = [
    ("http://192.168.50.21:11434", "huihui_ai/qwen3-abliterated:8b"),
    ("http://192.168.50.129:11434", "qwen3.5:9b"),
    ("http://localhost:11434", "huihui_ai/qwen3-abliterated:8b"),
]


def llm_generate(prompt: str, system: str = "", timeout: int = 60) -> str:
    """Generiere Text via Ollama — probiert alle Endpoints durch."""
    for endpoint, model in OLLAMA_ENDPOINTS:
        try:
            payload = json.dumps({
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 512},
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
            log.debug("LLM endpoint %s failed: %s", endpoint, e)
            continue
    return "[FEHLER: Kein LLM-Endpoint erreichbar]"


# ---------------------------------------------------------------------------
# Group-Evolving Engine
# ---------------------------------------------------------------------------

class GroupEvolvingEngine:
    """
    Closed-Loop Evolution Engine:
    Plan -> Execute -> Observe -> Evolve -> Share
    """

    SYSTEM_PROMPT = (
        "Du bist Teil des Way2AGI Self-Evolving Systems. "
        "Deine Aufgabe: Aus Erfahrungen lernen, Strategien verbessern, "
        "Wissen mit anderen Agenten teilen. Antworte auf Deutsch, kurz und praezise."
    )

    def __init__(self, db_path: str = "/data/elias-memory/memory.db") -> None:
        self.kg = KnowledgeGraph(db_path)
        self.agents = ["chief", "reasoner", "researcher", "archivist"]

    async def evolve_cycle(self, task: str, agent_id: str = "chief") -> Experience:
        """Fuehre einen kompletten Evolution-Zyklus durch."""
        log.info("GEA evolve_cycle start: task=%s agent=%s", task, agent_id)

        # Phase 1: PLAN
        plan = await self._phase_plan(task, agent_id)

        # Phase 2: EXECUTE
        result = await self._phase_execute(task, plan, agent_id)

        # Phase 3: OBSERVE
        score, observations = await self._phase_observe(task, plan, result, agent_id)

        # Phase 4: EVOLVE
        lessons = await self._phase_evolve(task, plan, result, score, observations, agent_id)

        # Phase 5: SHARE
        experience = Experience(
            agent_id=agent_id,
            task=task,
            approach=plan,
            outcome=result,
            score=score,
            lessons=lessons,
        )
        await self._phase_share(experience)

        log.info("GEA evolve_cycle complete: score=%.2f lessons=%d", score, len(lessons))
        return experience

    async def _phase_plan(self, task: str, agent_id: str) -> str:
        """Phase 1: Plane Ansatz basierend auf vergangenen Erfahrungen."""
        past = self.kg.get_agent_experiences(agent_id, limit=5)
        shared = self.kg.get_shared_knowledge("strategy", limit=5)

        context_parts = [f"Task: {task}"]
        if past:
            context_parts.append("Vergangene Erfahrungen:")
            for p in past[:3]:
                context_parts.append(f"  - {p['task']}: Score {p['score']:.1f}")
        if shared:
            context_parts.append("Geteiltes Wissen:")
            for s in shared[:3]:
                context_parts.append(f"  - {s['content'][:100]}")

        prompt = "\n".join(context_parts) + "\n\nErstelle einen konkreten Plan (max 5 Schritte):"

        plan = await asyncio.to_thread(llm_generate, prompt, self.SYSTEM_PROMPT)
        log.info("GEA PLAN: %s", plan[:200])
        return plan

    async def _phase_execute(self, task: str, plan: str, agent_id: str) -> str:
        """Phase 2: Fuehre Plan aus."""
        prompt = f"Task: {task}\nPlan: {plan}\n\nFuehre den Plan aus und beschreibe das Ergebnis:"
        result = await asyncio.to_thread(llm_generate, prompt, self.SYSTEM_PROMPT)
        log.info("GEA EXECUTE: %s", result[:200])
        return result

    async def _phase_observe(self, task: str, plan: str, result: str, agent_id: str) -> tuple[float, str]:
        """Phase 3: Beobachte und bewerte Ergebnis."""
        prompt = (
            f"Task: {task}\nPlan: {plan}\nErgebnis: {result}\n\n"
            "Bewerte das Ergebnis auf einer Skala von 0.0 bis 1.0 und erklaere warum.\n"
            "Format: SCORE: 0.X\nBEOBACHTUNG: ..."
        )
        observation = await asyncio.to_thread(llm_generate, prompt, self.SYSTEM_PROMPT)

        # Parse score
        score = 0.5
        for line in observation.splitlines():
            line = line.strip()
            if line.startswith("SCORE:"):
                try:
                    score = float(line.split(":")[1].strip())
                    score = max(0.0, min(1.0, score))
                except (ValueError, IndexError):
                    pass
                break

        log.info("GEA OBSERVE: score=%.2f", score)
        return score, observation

    async def _phase_evolve(
        self, task: str, plan: str, result: str,
        score: float, observations: str, agent_id: str,
    ) -> list[str]:
        """Phase 4: Extrahiere Lessons-Learned."""
        prompt = (
            f"Task: {task}\nScore: {score}\nBeobachtungen: {observations}\n\n"
            "Extrahiere 1-3 konkrete Lessons-Learned (je eine Zeile, mit - Prefix):"
        )
        response = await asyncio.to_thread(llm_generate, prompt, self.SYSTEM_PROMPT)

        lessons = []
        for line in response.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                lessons.append(line.lstrip("-* ").strip())
        if not lessons:
            lessons = [response.strip()[:200]]

        # Update evolution state
        state = self.kg.get_evolution_state(agent_id) or EvolutionState(agent_id=agent_id)
        state.generation += 1
        state.total_experiences += 1
        state.avg_score = (state.avg_score * (state.total_experiences - 1) + score) / state.total_experiences
        if score >= 0.8:
            state.best_strategies.append(plan[:200])
            state.best_strategies = state.best_strategies[-10:]  # Keep last 10
        if score < 0.4:
            state.weaknesses.extend(lessons)
            state.weaknesses = state.weaknesses[-10:]
        self.kg.update_evolution_state(state)

        log.info("GEA EVOLVE: generation=%d avg_score=%.2f lessons=%s", state.generation, state.avg_score, lessons)
        return lessons

    async def _phase_share(self, experience: Experience) -> None:
        """Phase 5: Teile Erfahrung mit anderen Agenten."""
        self.kg.store_experience(experience)

        # Teile besonders gute oder schlechte Erfahrungen
        if experience.score >= 0.7 or experience.score <= 0.3:
            for lesson in experience.lessons:
                ktype = "strategy" if experience.score >= 0.7 else "warning"
                self.kg.share_knowledge(
                    source=experience.agent_id,
                    ktype=ktype,
                    content=lesson,
                    relevance=experience.score,
                )
            log.info("GEA SHARE: %d lessons shared (type=%s)",
                     len(experience.lessons),
                     "strategy" if experience.score >= 0.7 else "warning")

    async def collective_evolve(self, task: str) -> list[Experience]:
        """Lasse alle Agenten parallel evolvieren und Erfahrungen teilen."""
        tasks = [self.evolve_cycle(task, agent_id=aid) for aid in self.agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        experiences = []
        for r in results:
            if isinstance(r, Experience):
                experiences.append(r)
            else:
                log.error("Agent evolution failed: %s", r)

        log.info("GEA collective_evolve: %d/%d agents completed",
                 len(experiences), len(self.agents))
        return experiences

    def get_evolution_report(self) -> dict[str, Any]:
        """Erstelle Bericht ueber den Evolution-Fortschritt."""
        report: dict[str, Any] = {"agents": {}, "shared_knowledge": {}}
        for agent_id in self.agents:
            state = self.kg.get_evolution_state(agent_id)
            if state:
                report["agents"][agent_id] = {
                    "generation": state.generation,
                    "total_experiences": state.total_experiences,
                    "avg_score": round(state.avg_score, 3),
                    "best_strategies": len(state.best_strategies),
                    "weaknesses": len(state.weaknesses),
                }
        for ktype in ("strategy", "warning"):
            knowledge = self.kg.get_shared_knowledge(ktype, limit=5)
            report["shared_knowledge"][ktype] = len(knowledge)
        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Way2AGI Group-Evolving Agents")
    parser.add_argument("--task", default="Analysiere das Way2AGI Memory-System und schlage Verbesserungen vor")
    parser.add_argument("--agent", default="chief")
    parser.add_argument("--collective", action="store_true", help="Alle Agenten parallel")
    parser.add_argument("--report", action="store_true", help="Evolution-Bericht anzeigen")
    parser.add_argument("--db", default="/data/elias-memory/memory.db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    engine = GroupEvolvingEngine(db_path=args.db)

    if args.report:
        report = engine.get_evolution_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.collective:
        results = asyncio.run(engine.collective_evolve(args.task))
        for exp in results:
            print(f"[{exp.agent_id}] Score: {exp.score:.2f} | Lessons: {exp.lessons}")
    else:
        result = asyncio.run(engine.evolve_cycle(args.task, agent_id=args.agent))
        print(f"Score: {result.score:.2f}")
        print(f"Lessons: {result.lessons}")
