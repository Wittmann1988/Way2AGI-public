"""
Way2AGI Consciousness Agent — Aktive Selbstbeobachtung mit messbarer Wirkung.

Mechanismen:
1. Wirkketten: Beobachtung -> Muster -> Regel -> Wirkung -> Messung
2. Intention Management: Persistente Ziele mit Decay
3. Curiosity Score: Vorhersagefehler als Neugier-Metrik
4. Confidence Gating: Unsicherheit erkennen und handeln
5. Research Queue: Hypothesen formulieren und testen
6. SVT: Systemverbesserungen vorschlagen und validieren
7. Self-Challenging: Schwierigkeits-Eskalation
8. Goal Generation: Eigene Verbesserungsziele

Usage:
  python -m agents.consciousness_agent --mode full --db /data/way2agi/memory/memory.db
  python -m agents.consciousness_agent --mode analyze  # Nur Analyse
  python -m agents.consciousness_agent --mode research  # Nur Forschung
  python -m agents.consciousness_agent --mode improve   # Nur SVT
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = os.environ.get("CONSCIOUSNESS_LOG_DIR", "/data/way2agi/memory/logs")
os.makedirs(LOG_DIR, exist_ok=True)

log = logging.getLogger("consciousness-agent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB = "/data/way2agi/memory/memory.db"
SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "training", "src", "consciousness_schema.sql"
)

# LLM endpoints (same order as agent_loop.py — Jetson first, Desktop second)
OLLAMA_ENDPOINTS = [
    ("http://YOUR_CONTROLLER_IP:11434", "huihui_ai/qwen3-abliterated:8b"),
    ("http://YOUR_DESKTOP_IP:11434", "qwen3.5:9b"),
    ("http://localhost:11434", "huihui_ai/qwen3-abliterated:8b"),
]

LLAMA_CPP_ENDPOINTS = [
    ("http://YOUR_CONTROLLER_IP:8080", "nemotron-3-nano:30b"),
    ("http://YOUR_DESKTOP_IP:8080", "lfm2:24b"),
]

# Thresholds
CURIOSITY_THRESHOLD = 0.6      # Above this -> enqueue research
CONFIDENCE_LOW = 0.4            # Below this -> deeper analysis or roundtable
INTENTION_DECAY_INTERVAL_H = 6  # Hours between decay ticks
MAX_ACTIVE_INTENTIONS = 15
MAX_RESEARCH_QUEUE = 30
SELF_CHALLENGE_ESCALATION = 0.15  # Difficulty bump per success


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

class ConsciousnessDB:
    """Thin wrapper around the elias-memory SQLite database."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Apply consciousness schema if tables are missing."""
        # Check if our tables exist
        tables = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        needed = {"intentions", "consciousness_log", "research_queue", "system_improvements"}
        if needed.issubset(tables):
            return

        schema_file = Path(SCHEMA_PATH)
        if schema_file.exists():
            sql = schema_file.read_text()
        else:
            # Inline fallback if schema file not found
            sql = _INLINE_SCHEMA
        self.conn.executescript(sql)
        self.conn.commit()
        log.info("Consciousness schema applied (%s)", self.db_path)

    # --- Generic helpers ---

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# Inline schema as fallback
_INLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS intentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    priority REAL DEFAULT 0.5,
    decay_rate REAL DEFAULT 0.05,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activated TIMESTAMP,
    linked_goal TEXT,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'consciousness',
    impact_score REAL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS consciousness_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decision_type TEXT NOT NULL,
    curiosity_score REAL,
    confidence_score REAL,
    observation TEXT,
    action_taken TEXT,
    expected_outcome TEXT,
    actual_outcome TEXT,
    kpi_impact REAL,
    wirkkette TEXT
);
CREATE TABLE IF NOT EXISTS research_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis TEXT NOT NULL,
    priority REAL DEFAULT 0.5,
    curiosity_score REAL,
    status TEXT DEFAULT 'pending',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started TIMESTAMP,
    completed TIMESTAMP,
    result TEXT,
    validated INTEGER DEFAULT 0,
    improvement_pct REAL
);
CREATE TABLE IF NOT EXISTS system_improvements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_by TEXT DEFAULT 'consciousness',
    description TEXT NOT NULL,
    category TEXT,
    test_method TEXT,
    baseline_value REAL,
    improved_value REAL,
    improvement_pct REAL,
    status TEXT DEFAULT 'proposed',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated TIMESTAMP,
    deployed TIMESTAMP
);
"""


# ---------------------------------------------------------------------------
# LLM caller (stdlib only, no dependencies)
# ---------------------------------------------------------------------------

def call_llm(prompt: str, system: str = "", max_tokens: int = 1024, timeout: int = 60) -> Optional[str]:
    """
    Call an LLM endpoint. Tries llama.cpp first, then Ollama.
    Returns the response text or None if all endpoints fail.
    """
    # 1. Try llama.cpp (OpenAI-compatible)
    for base_url, model in LLAMA_CPP_ENDPOINTS:
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            payload = json.dumps({
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": False,
                "temperature": 0.3,
            }).encode()

            req = urllib.request.Request(
                f"{base_url}/v1/chat/completions",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                text = data["choices"][0]["message"]["content"].strip()
                if text:
                    log.debug("LLM response via llama.cpp %s (%d chars)", base_url, len(text))
                    return text
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, IndexError):
            continue

    # 2. Fallback: Ollama
    for base_url, model in OLLAMA_ENDPOINTS:
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": (system or "Antworte praezise und kurz.") + " /no_think"},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.3},
            }).encode()

            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                text = data.get("message", {}).get("content", "").strip()
                if text:
                    log.debug("LLM response via Ollama %s (%d chars)", base_url, len(text))
                    return text
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
            continue

    log.warning("All LLM endpoints unreachable")
    return None


def extract_json(text: str) -> Optional[dict | list]:
    """Extract JSON from a text that may contain prose around it."""
    if not text:
        return None
    # Try the whole string first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Find JSON object
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# Consciousness Agent
# ---------------------------------------------------------------------------

class ConsciousnessAgent:
    """
    The Consciousness Agent observes, reflects, and improves the Way2AGI system.

    It writes concrete entries into the DB that other agents (Orchestrator,
    AgentLoop, GoalGuard) read and act upon.
    """

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db = ConsciousnessDB(db_path)
        self.run_timestamp = datetime.now()
        log.info("ConsciousnessAgent initialized (db: %s)", db_path)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------
    # 0. Consciousness Log — every action gets logged
    # ------------------------------------------------------------------

    def _log_decision(
        self,
        decision_type: str,
        observation: str,
        action_taken: str,
        expected_outcome: str = "",
        curiosity_score: float = 0.0,
        confidence_score: float = 1.0,
        kpi_impact: float = 0.0,
        wirkkette: str = "",
    ) -> int:
        """Write an entry to consciousness_log. Returns the row id."""
        cur = self.db.execute(
            """INSERT INTO consciousness_log
               (decision_type, curiosity_score, confidence_score, observation,
                action_taken, expected_outcome, kpi_impact, wirkkette)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_type,
                curiosity_score,
                confidence_score,
                observation[:2000],
                action_taken[:2000],
                expected_outcome[:1000],
                kpi_impact,
                wirkkette[:2000],
            ),
        )
        self.db.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # 1. Wirkketten-System
    # ------------------------------------------------------------------

    def analyze_wirkketten(self) -> list[dict[str, Any]]:
        """
        Observe patterns in action_log and error history.
        Detect recurring failures, generate rules, write them to the rules table.

        Wirkkette: Beobachtung -> Muster -> Regel -> Orchestrator liest -> Routing aendert sich
        """
        chains: list[dict[str, Any]] = []

        # a) Analyze recent errors — recurring ones become rules
        errors = self.db.fetchall(
            """SELECT error_code, description, occurrence_count, category, prevention
               FROM errors
               WHERE status = 'open' AND occurrence_count >= 2
               ORDER BY occurrence_count DESC
               LIMIT 10"""
        )

        for err in errors:
            observation = (
                f"Fehler {err['error_code']} tritt wiederholt auf "
                f"({err['occurrence_count']}x): {err['description'][:200]}"
            )

            # Check if a rule already exists for this error
            existing = self.db.fetchone(
                "SELECT id FROM rules WHERE condition LIKE ? AND status='active'",
                (f"%{err['error_code']}%",),
            )
            if existing:
                continue

            # Generate a rule via LLM
            rule_text = self._generate_rule_for_error(err)
            if not rule_text:
                # Fallback: use prevention field or generic rule
                rule_text = err["prevention"] or f"Fehler {err['error_code']} vermeiden: {err['description'][:100]}"

            # Write rule to rules table (readable by Orchestrator/GoalGuard)
            rule_id = f"R-AUTO-{err['error_code']}"
            self.db.execute(
                """INSERT OR IGNORE INTO rules (id, rule_text, source, priority, condition, action, status)
                   VALUES (?, ?, 'consciousness', 60, ?, ?, 'active')""",
                (
                    rule_id,
                    rule_text[:500],
                    f"error:{err['error_code']}",
                    f"Apply prevention: {rule_text[:200]}",
                ),
            )
            self.db.commit()

            wirkkette = (
                f"Beobachtung: {observation} -> "
                f"Muster: Wiederholter Fehler -> "
                f"Regel: {rule_id} erstellt -> "
                f"Wirkung: Orchestrator/GoalGuard liest Regel"
            )

            self._log_decision(
                decision_type="wirkkette_rule_creation",
                observation=observation,
                action_taken=f"Regel {rule_id} erstellt: {rule_text[:200]}",
                expected_outcome="Fehlerrate fuer diesen Typ sinkt",
                confidence_score=0.7,
                wirkkette=wirkkette,
            )
            chains.append({"error_code": err["error_code"], "rule_id": rule_id, "wirkkette": wirkkette})

        # b) Analyze action_log for slow or failed patterns
        slow_patterns = self.db.fetchall(
            """SELECT module, model_used, device,
                      COUNT(*) as total,
                      SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures,
                      AVG(duration_ms) as avg_ms
               FROM action_log
               WHERE timestamp > datetime('now', '-24 hours')
               GROUP BY module, model_used, device
               HAVING failures > 2 OR avg_ms > 30000
               ORDER BY failures DESC
               LIMIT 5"""
        )

        for pat in slow_patterns:
            fail_rate = (pat["failures"] / pat["total"]) if pat["total"] > 0 else 0
            observation = (
                f"Modul {pat['module']} auf {pat['device']}/{pat['model_used']}: "
                f"{pat['failures']}/{pat['total']} Fehler ({fail_rate:.0%}), "
                f"avg {pat['avg_ms']:.0f}ms"
            )

            # Create an intention to fix this
            if fail_rate > 0.3:
                intent_desc = f"Routing fuer {pat['module']} optimieren — weg von {pat['device']}/{pat['model_used']} (Fehlerrate {fail_rate:.0%})"
                self._create_intention(intent_desc, priority=0.7 + fail_rate * 0.2, linked_goal="routing_optimization")

            wirkkette = (
                f"Beobachtung: {observation} -> "
                f"Muster: Hohe Fehlerrate/Latenz -> "
                f"Intention: Routing optimieren -> "
                f"Wirkung: Orchestrator bevorzugt andere Nodes"
            )
            self._log_decision(
                decision_type="wirkkette_performance",
                observation=observation,
                action_taken="Intention fuer Routing-Optimierung erstellt",
                expected_outcome="Fehlerrate sinkt, Latenz verbessert sich",
                confidence_score=0.6,
                wirkkette=wirkkette,
            )
            chains.append({"pattern": observation, "wirkkette": wirkkette})

        # c) Check if previous wirkketten had measurable impact
        self._evaluate_past_wirkketten()

        log.info("Wirkketten-Analyse: %d neue Ketten identifiziert", len(chains))
        return chains

    def _generate_rule_for_error(self, error_row: sqlite3.Row) -> Optional[str]:
        """Ask an LLM to generate a prevention rule for a recurring error."""
        prompt = (
            f"Du bist ein System-Optimierer. Ein Fehler tritt wiederholt auf:\n"
            f"Code: {error_row['error_code']}\n"
            f"Beschreibung: {error_row['description'][:300]}\n"
            f"Kategorie: {error_row['category']}\n"
            f"Haeufigkeit: {error_row['occurrence_count']}x\n\n"
            f"Formuliere EINE praezise Regel (max 1 Satz) die diesen Fehler verhindert. "
            f"Die Regel wird von einem Orchestrator-Agent gelesen und automatisch angewendet."
        )
        response = call_llm(prompt, system="Antworte NUR mit der Regel. Kein JSON, kein Markdown.")
        if response:
            # Clean up: take first meaningful line
            for line in response.strip().split("\n"):
                line = line.strip().lstrip("-").lstrip("*").strip()
                if len(line) > 15:
                    return line
        return None

    def _evaluate_past_wirkketten(self) -> None:
        """Check if rules created by past wirkketten actually reduced errors."""
        auto_rules = self.db.fetchall(
            """SELECT id, condition FROM rules
               WHERE source='consciousness' AND status='active'
               AND created_at < datetime('now', '-12 hours')"""
        )
        for rule in auto_rules:
            # Extract error code from condition
            cond = rule["condition"] or ""
            if not cond.startswith("error:"):
                continue
            error_code = cond.replace("error:", "").strip()

            # Check if that error still occurs frequently
            recent = self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM action_log
                   WHERE success=0 AND input_summary LIKE ?
                   AND timestamp > datetime('now', '-12 hours')""",
                (f"%{error_code}%",),
            )
            if recent and recent["cnt"] == 0:
                # Rule is working — log positive impact
                self._log_decision(
                    decision_type="wirkkette_validation",
                    observation=f"Regel {rule['id']} wirkt: Fehler {error_code} nicht mehr aufgetreten",
                    action_taken="Regel bleibt aktiv",
                    kpi_impact=0.1,
                    wirkkette=f"Regel {rule['id']} -> Fehler {error_code} eliminiert",
                )

    # ------------------------------------------------------------------
    # 2. Intention Management
    # ------------------------------------------------------------------

    def _create_intention(
        self,
        description: str,
        priority: float = 0.5,
        linked_goal: str = "",
        source: str = "consciousness",
        decay_rate: float = 0.05,
    ) -> int:
        """Create a new intention. Returns its id."""
        # Check for duplicates
        existing = self.db.fetchone(
            "SELECT id FROM intentions WHERE description = ? AND status = 'active'",
            (description,),
        )
        if existing:
            # Reinforce: bump priority
            self.db.execute(
                "UPDATE intentions SET priority = MIN(1.0, priority + 0.1), last_activated = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
            self.db.commit()
            return existing["id"]

        # Enforce cap
        active_count = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM intentions WHERE status='active'"
        )
        if active_count and active_count["cnt"] >= MAX_ACTIVE_INTENTIONS:
            # Deactivate lowest priority
            self.db.execute(
                """UPDATE intentions SET status='decayed'
                   WHERE id = (
                       SELECT id FROM intentions WHERE status='active'
                       ORDER BY priority ASC LIMIT 1
                   )"""
            )

        cur = self.db.execute(
            """INSERT INTO intentions (description, priority, decay_rate, linked_goal, source, last_activated)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (description[:500], min(1.0, max(0.0, priority)), decay_rate, linked_goal, source),
        )
        self.db.commit()
        log.info("Intention created: %s (prio=%.2f)", description[:80], priority)
        return cur.lastrowid

    def manage_intentions(self) -> dict[str, Any]:
        """
        Decay inactive intentions, activate relevant ones, deactivate expired ones.
        Returns summary of changes.
        """
        changes = {"decayed": 0, "activated": 0, "deactivated": 0}

        # Decay: reduce priority of intentions not activated recently
        active = self.db.fetchall(
            "SELECT id, priority, decay_rate, last_activated FROM intentions WHERE status='active'"
        )
        for intent in active:
            last = intent["last_activated"]
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    hours_since = (self.run_timestamp - last_dt).total_seconds() / 3600
                except (ValueError, TypeError):
                    hours_since = INTENTION_DECAY_INTERVAL_H
            else:
                hours_since = INTENTION_DECAY_INTERVAL_H

            if hours_since >= INTENTION_DECAY_INTERVAL_H:
                decay_ticks = hours_since / INTENTION_DECAY_INTERVAL_H
                new_priority = intent["priority"] - (intent["decay_rate"] * decay_ticks)

                if new_priority <= 0.05:
                    self.db.execute(
                        "UPDATE intentions SET status='decayed', priority=0.0 WHERE id=?",
                        (intent["id"],),
                    )
                    changes["decayed"] += 1
                else:
                    self.db.execute(
                        "UPDATE intentions SET priority=? WHERE id=?",
                        (max(0.0, new_priority), intent["id"]),
                    )

        self.db.commit()

        # Generate report of top active intentions (for Orchestrator to read)
        top = self.db.fetchall(
            """SELECT id, description, priority, linked_goal
               FROM intentions WHERE status='active'
               ORDER BY priority DESC LIMIT 5"""
        )
        top_list = [
            {"id": r["id"], "description": r["description"], "priority": r["priority"], "goal": r["linked_goal"]}
            for r in top
        ]

        self._log_decision(
            decision_type="intention_management",
            observation=f"{len(active)} aktive Intentionen, {changes['decayed']} verfallen",
            action_taken=f"Top-5 Intentionen aktualisiert",
            expected_outcome="Orchestrator nutzt Top-Intentionen fuer Priorisierung",
        )

        log.info(
            "Intentions: %d active, %d decayed, top: %s",
            len(active) - changes["decayed"],
            changes["decayed"],
            [t["description"][:40] for t in top_list],
        )
        return {"changes": changes, "top_intentions": top_list}

    def get_active_intentions(self) -> list[dict[str, Any]]:
        """Return active intentions, ordered by priority. Used by Orchestrator."""
        rows = self.db.fetchall(
            """SELECT id, description, priority, linked_goal, source
               FROM intentions WHERE status='active'
               ORDER BY priority DESC"""
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 3. Curiosity Score
    # ------------------------------------------------------------------

    def compute_curiosity_scores(self) -> list[dict[str, Any]]:
        """
        Curiosity = |expected_outcome - actual_outcome| for recent decisions.
        High curiosity = prediction was wrong = we should investigate more.
        Returns items with high curiosity that should be researched.
        """
        curious_items: list[dict[str, Any]] = []

        # Look at consciousness_log entries that have both expected and actual outcomes
        rows = self.db.fetchall(
            """SELECT id, decision_type, expected_outcome, actual_outcome, observation
               FROM consciousness_log
               WHERE expected_outcome IS NOT NULL
                 AND expected_outcome != ''
                 AND actual_outcome IS NOT NULL
                 AND actual_outcome != ''
               ORDER BY id DESC
               LIMIT 50"""
        )

        for row in rows:
            score = self._compute_single_curiosity(row["expected_outcome"], row["actual_outcome"])
            if score >= CURIOSITY_THRESHOLD:
                curious_items.append({
                    "log_id": row["id"],
                    "decision_type": row["decision_type"],
                    "curiosity_score": score,
                    "observation": row["observation"],
                    "expected": row["expected_outcome"],
                    "actual": row["actual_outcome"],
                })
                # Update the score in the log
                self.db.execute(
                    "UPDATE consciousness_log SET curiosity_score=? WHERE id=?",
                    (score, row["id"]),
                )

        self.db.commit()

        # Also compute curiosity from knowledge gaps (topics with few memories)
        gap_items = self._curiosity_from_knowledge_gaps()
        curious_items.extend(gap_items)

        # Enqueue high-curiosity items as research hypotheses
        for item in curious_items:
            self._enqueue_research(
                hypothesis=f"Untersuchen warum {item.get('decision_type', 'Unbekannt')}: "
                           f"Erwartet '{item.get('expected', '')[:100]}' vs "
                           f"Tatsaechlich '{item.get('actual', '')[:100]}'",
                curiosity_score=item["curiosity_score"],
                priority=item["curiosity_score"],
            )

        log.info("Curiosity: %d items above threshold %.2f", len(curious_items), CURIOSITY_THRESHOLD)
        return curious_items

    def _compute_single_curiosity(self, expected: str, actual: str) -> float:
        """
        Compute curiosity as semantic distance between expected and actual.
        Simple heuristic: word overlap ratio. 1.0 = completely different, 0.0 = identical.
        """
        if expected == actual:
            return 0.0

        exp_words = set(expected.lower().split())
        act_words = set(actual.lower().split())

        if not exp_words and not act_words:
            return 0.0

        union = exp_words | act_words
        intersection = exp_words & act_words

        if not union:
            return 0.0

        # Jaccard distance
        overlap = len(intersection) / len(union)
        curiosity = 1.0 - overlap
        return round(min(1.0, curiosity), 3)

    def _curiosity_from_knowledge_gaps(self) -> list[dict[str, Any]]:
        """Detect topics with very few memories — high curiosity about unknowns."""
        items = []
        try:
            rows = self.db.fetchall(
                """SELECT
                       COALESCE(json_extract(metadata, '$.topic'), 'general') as topic,
                       COUNT(*) as cnt
                   FROM memories
                   GROUP BY topic
                   HAVING cnt < 3
                   ORDER BY cnt ASC
                   LIMIT 5"""
            )
            for row in rows:
                score = max(0.5, 1.0 - (row["cnt"] / 5.0))
                items.append({
                    "decision_type": "knowledge_gap",
                    "curiosity_score": score,
                    "observation": f"Topic '{row['topic']}' hat nur {row['cnt']} Memories",
                    "expected": "Mindestens 5 Memories pro relevantes Topic",
                    "actual": f"Nur {row['cnt']} vorhanden",
                })
        except sqlite3.OperationalError:
            # memories table might have different schema
            pass
        return items

    # ------------------------------------------------------------------
    # 4. Confidence Gating
    # ------------------------------------------------------------------

    def evaluate_confidence(self) -> list[dict[str, Any]]:
        """
        Evaluate system confidence for recent decisions.
        Low confidence triggers deeper analysis or roundtable.
        """
        low_confidence: list[dict[str, Any]] = []

        # Check recent action_log for patterns of failure that indicate low confidence
        rows = self.db.fetchall(
            """SELECT module, model_used,
                      COUNT(*) as total,
                      SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes
               FROM action_log
               WHERE timestamp > datetime('now', '-6 hours')
               GROUP BY module, model_used
               HAVING total >= 3"""
        )

        for row in rows:
            success_rate = row["successes"] / row["total"] if row["total"] > 0 else 0
            confidence = success_rate  # Simple: confidence = success rate

            if confidence < CONFIDENCE_LOW:
                item = {
                    "module": row["module"],
                    "model": row["model_used"],
                    "confidence": round(confidence, 3),
                    "total_actions": row["total"],
                    "successes": row["successes"],
                    "action": "needs_deeper_analysis",
                }

                # Create a TODO for deeper investigation
                todo_title = f"Confidence niedrig fuer {row['module']}/{row['model_used']} ({confidence:.0%})"
                existing_todo = self.db.fetchone(
                    "SELECT id FROM todos WHERE title = ? AND status IN ('open', 'in_progress')",
                    (todo_title,),
                )
                if not existing_todo:
                    import uuid
                    todo_id = f"C-{uuid.uuid4().hex[:6].upper()}"
                    self.db.execute(
                        """INSERT INTO todos (id, title, description, priority, category, source)
                           VALUES (?, ?, ?, ?, 'investigation', 'consciousness')""",
                        (
                            todo_id,
                            todo_title,
                            f"Confidence {confidence:.0%} ({row['successes']}/{row['total']} Erfolge). "
                            f"Tiefere Analyse oder Roundtable noetig um Ursache zu finden.",
                            70,
                        ),
                    )
                    self.db.commit()
                    item["todo_id"] = todo_id
                    item["action"] = "todo_created"

                self._log_decision(
                    decision_type="confidence_gating",
                    observation=f"{row['module']}/{row['model_used']}: {confidence:.0%} confidence",
                    action_taken=item["action"],
                    confidence_score=confidence,
                    expected_outcome="Ursache wird identifiziert und behoben",
                )
                low_confidence.append(item)

        # Also check model evaluations if available
        try:
            eval_rows = self.db.fetchall(
                """SELECT model_name, task_type, AVG(quality_score) as avg_q
                   FROM model_evaluations
                   WHERE test_date > datetime('now', '-7 days')
                   GROUP BY model_name, task_type
                   HAVING avg_q < 0.5"""
            )
            for ev in eval_rows:
                low_confidence.append({
                    "module": "model_evaluation",
                    "model": ev["model_name"],
                    "task_type": ev["task_type"],
                    "confidence": round(ev["avg_q"], 3),
                    "action": "model_underperforming",
                })
        except sqlite3.OperationalError:
            pass

        log.info("Confidence gating: %d low-confidence areas found", len(low_confidence))
        return low_confidence

    # ------------------------------------------------------------------
    # 5. Research Queue
    # ------------------------------------------------------------------

    def _enqueue_research(
        self,
        hypothesis: str,
        curiosity_score: float = 0.5,
        priority: float = 0.5,
    ) -> Optional[int]:
        """Add a hypothesis to the research queue if not already there."""
        # Check for duplicates (fuzzy: first 100 chars)
        key = hypothesis[:100]
        existing = self.db.fetchone(
            "SELECT id FROM research_queue WHERE hypothesis LIKE ? AND status IN ('pending', 'in_progress')",
            (f"{key}%",),
        )
        if existing:
            # Bump priority
            self.db.execute(
                "UPDATE research_queue SET priority = MIN(1.0, priority + 0.1) WHERE id = ?",
                (existing["id"],),
            )
            self.db.commit()
            return existing["id"]

        # Enforce cap
        pending_count = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM research_queue WHERE status='pending'"
        )
        if pending_count and pending_count["cnt"] >= MAX_RESEARCH_QUEUE:
            # Remove lowest priority
            self.db.execute(
                """DELETE FROM research_queue WHERE id = (
                       SELECT id FROM research_queue WHERE status='pending'
                       ORDER BY priority ASC LIMIT 1
                   )"""
            )

        cur = self.db.execute(
            """INSERT INTO research_queue (hypothesis, priority, curiosity_score)
               VALUES (?, ?, ?)""",
            (hypothesis[:1000], min(1.0, priority), curiosity_score),
        )
        self.db.commit()
        return cur.lastrowid

    def process_research_queue(self, max_items: int = 3) -> list[dict[str, Any]]:
        """
        Take top-priority research items, investigate them via LLM,
        and write results back.
        """
        results: list[dict[str, Any]] = []

        items = self.db.fetchall(
            """SELECT id, hypothesis, curiosity_score, priority
               FROM research_queue
               WHERE status = 'pending'
               ORDER BY priority DESC
               LIMIT ?""",
            (max_items,),
        )

        for item in items:
            # Mark as in progress
            self.db.execute(
                "UPDATE research_queue SET status='in_progress', started=CURRENT_TIMESTAMP WHERE id=?",
                (item["id"],),
            )
            self.db.commit()

            # Investigate via LLM
            result = self._investigate_hypothesis(item["hypothesis"])

            if result:
                self.db.execute(
                    """UPDATE research_queue
                       SET status='completed', completed=CURRENT_TIMESTAMP,
                           result=?, validated=0
                       WHERE id=?""",
                    (result[:2000], item["id"]),
                )

                # If the result suggests an improvement, create an SVT entry
                improvement = self._extract_improvement(item["hypothesis"], result)
                if improvement:
                    self._propose_improvement(
                        description=improvement["description"],
                        category=improvement.get("category", "general"),
                        test_method=improvement.get("test_method", ""),
                    )

                results.append({
                    "id": item["id"],
                    "hypothesis": item["hypothesis"],
                    "result": result[:300],
                    "improvement_proposed": improvement is not None,
                })
            else:
                self.db.execute(
                    "UPDATE research_queue SET status='failed', result='LLM nicht erreichbar' WHERE id=?",
                    (item["id"],),
                )

            self.db.commit()

            self._log_decision(
                decision_type="research_investigation",
                observation=item["hypothesis"][:300],
                action_taken=f"Recherche {'abgeschlossen' if result else 'fehlgeschlagen'}",
                curiosity_score=item["curiosity_score"],
                expected_outcome="Neues Wissen oder Verbesserungsvorschlag",
            )

        log.info("Research: %d items processed", len(results))
        return results

    def _investigate_hypothesis(self, hypothesis: str) -> Optional[str]:
        """Use an LLM to investigate a hypothesis."""
        prompt = (
            f"Du bist ein Forschungs-Agent im Way2AGI System.\n\n"
            f"HYPOTHESE: {hypothesis}\n\n"
            f"Untersuche diese Hypothese:\n"
            f"1. Was koennte die Ursache sein?\n"
            f"2. Welche Loesung gibt es?\n"
            f"3. Wie kann man die Loesung testen?\n"
            f"4. Welche Verbesserung (in %) ist realistisch?\n\n"
            f"Antworte strukturiert und konkret (max 300 Woerter)."
        )
        return call_llm(prompt, system="Du bist ein praeziser System-Analyst. Kurze, actionable Antworten.")

    def _extract_improvement(self, hypothesis: str, result: str) -> Optional[dict[str, str]]:
        """Extract a concrete improvement proposal from research results."""
        prompt = (
            f"Basierend auf dieser Forschung:\n"
            f"Hypothese: {hypothesis[:200]}\n"
            f"Ergebnis: {result[:500]}\n\n"
            f"Extrahiere EINE konkrete Verbesserung als JSON:\n"
            f'{{"description": "...", "category": "routing|memory|training|agent|performance", '
            f'"test_method": "Wie testen?", "expected_improvement_pct": 0-100}}\n'
            f"Antworte NUR mit dem JSON. Falls keine Verbesserung moeglich: {{}}"
        )
        response = call_llm(prompt, system="Antworte NUR mit JSON.", max_tokens=300)
        data = extract_json(response)
        if isinstance(data, dict) and data.get("description"):
            return data
        return None

    # ------------------------------------------------------------------
    # 6. System Verbesserungs Tracker (SVT)
    # ------------------------------------------------------------------

    def _propose_improvement(
        self,
        description: str,
        category: str = "general",
        test_method: str = "",
        proposed_by: str = "consciousness",
    ) -> int:
        """Propose a system improvement. Returns the row id."""
        # Check for duplicates
        existing = self.db.fetchone(
            "SELECT id FROM system_improvements WHERE description = ? AND status IN ('proposed', 'testing')",
            (description,),
        )
        if existing:
            return existing["id"]

        cur = self.db.execute(
            """INSERT INTO system_improvements (proposed_by, description, category, test_method)
               VALUES (?, ?, ?, ?)""",
            (proposed_by, description[:1000], category, test_method[:500]),
        )
        self.db.commit()
        log.info("SVT proposal: %s [%s]", description[:80], category)
        return cur.lastrowid

    def process_improvements(self) -> list[dict[str, Any]]:
        """
        Review proposed improvements, test if possible, update status.
        Creates TODOs for improvements that need human validation.
        """
        results: list[dict[str, Any]] = []

        # Get proposed improvements
        proposals = self.db.fetchall(
            """SELECT id, description, category, test_method, baseline_value
               FROM system_improvements
               WHERE status = 'proposed'
               ORDER BY created DESC
               LIMIT 5"""
        )

        for prop in proposals:
            # Try to get a baseline measurement
            baseline = self._measure_baseline(prop["category"])

            if baseline is not None:
                self.db.execute(
                    "UPDATE system_improvements SET baseline_value=?, status='testing' WHERE id=?",
                    (baseline, prop["id"]),
                )
            else:
                # No automatic baseline possible — create TODO for manual validation
                import uuid
                todo_id = f"SVT-{uuid.uuid4().hex[:6].upper()}"
                self.db.execute(
                    """INSERT OR IGNORE INTO todos (id, title, description, priority, category, source)
                       VALUES (?, ?, ?, ?, 'improvement', 'consciousness')""",
                    (
                        todo_id,
                        f"SVT validieren: {prop['description'][:60]}",
                        f"Verbesserungsvorschlag: {prop['description']}\n"
                        f"Kategorie: {prop['category']}\n"
                        f"Testmethode: {prop['test_method']}\n"
                        f"Braucht manuelle Validierung oder A/B-Test.",
                        60,
                    ),
                )
                self.db.execute(
                    "UPDATE system_improvements SET status='needs_validation' WHERE id=?",
                    (prop["id"],),
                )

            self.db.commit()
            results.append({
                "id": prop["id"],
                "description": prop["description"][:200],
                "baseline": baseline,
                "status": "testing" if baseline is not None else "needs_validation",
            })

            self._log_decision(
                decision_type="svt_processing",
                observation=f"SVT #{prop['id']}: {prop['description'][:200]}",
                action_taken=f"Baseline: {baseline}, Status: {'testing' if baseline else 'needs_validation'}",
                expected_outcome="Messbare Verbesserung nach Deployment",
            )

        # Also check testing improvements for completion
        self._check_testing_improvements()

        log.info("SVT: %d proposals processed", len(results))
        return results

    def _measure_baseline(self, category: str) -> Optional[float]:
        """
        Measure current system performance as a baseline for the given category.
        Returns a score between 0 and 1, or None if not measurable.
        """
        if category == "routing":
            row = self.db.fetchone(
                """SELECT
                       CAST(SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) as rate
                   FROM action_log
                   WHERE timestamp > datetime('now', '-24 hours')
                   AND module IN ('orchestrator', 'smart_router', 'agent_loop')"""
            )
            return row["rate"] if row and row["rate"] is not None else None

        if category == "memory":
            row = self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM memories WHERE importance > 0.5"
            )
            # Normalize to 0-1 scale (more high-importance memories = better)
            return min(1.0, (row["cnt"] / 100.0)) if row else None

        if category == "performance":
            row = self.db.fetchone(
                """SELECT AVG(duration_ms) as avg_ms FROM action_log
                   WHERE timestamp > datetime('now', '-24 hours')
                   AND duration_ms IS NOT NULL AND duration_ms > 0"""
            )
            if row and row["avg_ms"]:
                # Lower is better: 1.0 at 0ms, 0.0 at 60s
                return max(0.0, 1.0 - (row["avg_ms"] / 60000.0))
            return None

        if category == "training":
            row = self.db.fetchone(
                """SELECT AVG(quality_score) as avg_q FROM model_evaluations
                   WHERE test_date > datetime('now', '-7 days')"""
            )
            return row["avg_q"] if row and row["avg_q"] is not None else None

        return None

    def _check_testing_improvements(self) -> None:
        """Check if improvements in 'testing' status can be validated."""
        testing = self.db.fetchall(
            """SELECT id, category, baseline_value, created
               FROM system_improvements
               WHERE status = 'testing'
               AND created < datetime('now', '-6 hours')"""
        )
        for item in testing:
            current = self._measure_baseline(item["category"])
            if current is None:
                continue

            improvement_pct = 0.0
            if item["baseline_value"] and item["baseline_value"] > 0:
                improvement_pct = ((current - item["baseline_value"]) / item["baseline_value"]) * 100

            self.db.execute(
                """UPDATE system_improvements
                   SET improved_value=?, improvement_pct=?,
                       status=CASE WHEN ? > 0 THEN 'validated' ELSE 'no_improvement' END,
                       validated=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (current, improvement_pct, improvement_pct, item["id"]),
            )
            self.db.commit()

            if improvement_pct > 0:
                self._log_decision(
                    decision_type="svt_validation",
                    observation=f"SVT #{item['id']}: {improvement_pct:.1f}% Verbesserung",
                    action_taken="Verbesserung validiert",
                    kpi_impact=improvement_pct / 100.0,
                )

    # ------------------------------------------------------------------
    # 7. Self-Challenging
    # ------------------------------------------------------------------

    def generate_self_challenges(self) -> list[dict[str, Any]]:
        """
        Generate progressively harder tasks for the system.
        Based on current success rates — if we're good at something,
        make it harder. If we're bad, practice more.
        """
        challenges: list[dict[str, Any]] = []

        # Get success rates by task type from action_log
        task_stats = self.db.fetchall(
            """SELECT
                   CASE
                       WHEN input_summary LIKE '%coding%' OR input_summary LIKE '%python%' THEN 'coding'
                       WHEN input_summary LIKE '%research%' OR input_summary LIKE '%arxiv%' THEN 'research'
                       WHEN input_summary LIKE '%routing%' OR input_summary LIKE '%model%' THEN 'routing'
                       WHEN input_summary LIKE '%memory%' OR input_summary LIKE '%recall%' THEN 'memory'
                       ELSE 'general'
                   END as task_type,
                   COUNT(*) as total,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes
               FROM action_log
               WHERE timestamp > datetime('now', '-7 days')
               GROUP BY task_type
               HAVING total >= 3"""
        )

        for stat in task_stats:
            success_rate = stat["successes"] / stat["total"] if stat["total"] > 0 else 0
            task_type = stat["task_type"]

            if success_rate > 0.8:
                # Good at this — escalate difficulty
                challenge = self._escalate_challenge(task_type, success_rate)
            elif success_rate < 0.5:
                # Bad at this — practice fundamentals
                challenge = self._practice_challenge(task_type, success_rate)
            else:
                continue

            if challenge:
                challenges.append(challenge)
                # Create as TODO
                import uuid
                todo_id = f"SC-{uuid.uuid4().hex[:6].upper()}"
                self.db.execute(
                    """INSERT OR IGNORE INTO todos (id, title, description, priority, category, source)
                       VALUES (?, ?, ?, ?, 'self_challenge', 'consciousness')""",
                    (
                        todo_id,
                        f"Self-Challenge: {challenge['title'][:60]}",
                        challenge["description"],
                        challenge["priority"],
                    ),
                )
                self.db.commit()
                challenge["todo_id"] = todo_id

        self._log_decision(
            decision_type="self_challenge_generation",
            observation=f"{len(task_stats)} Task-Typen analysiert",
            action_taken=f"{len(challenges)} Challenges generiert",
            expected_outcome="System-Faehigkeiten wachsen durch gezielte Uebung",
        )

        log.info("Self-challenges: %d generated", len(challenges))
        return challenges

    def _escalate_challenge(self, task_type: str, current_rate: float) -> Optional[dict[str, Any]]:
        """Generate a harder challenge for a task type we're good at."""
        escalation_map = {
            "coding": [
                "Multi-File Refactoring mit Abhaengigkeits-Analyse",
                "Concurrent Python Code mit asyncio und Error Recovery",
                "Cross-Language Integration (Python + TypeScript + SQL)",
            ],
            "research": [
                "3 arXiv Papers vergleichen und Synthese erstellen",
                "Research-Findings in lauffaehigen Code uebersetzen",
                "Eigene Hypothese formulieren und experimentell testen",
            ],
            "routing": [
                "Routing-Entscheidung mit 5+ konkurrierenden Constraints optimieren",
                "Latenz-basiertes dynamisches Routing implementieren",
                "A/B-Test fuer Routing-Strategien aufsetzen",
            ],
            "memory": [
                "Memory-Consolidation mit Widerspruchs-Erkennung",
                "Temporales Reasoning ueber Memory-Ketten",
                "Automatische Memory-Pruning-Strategie mit Impact-Messung",
            ],
            "general": [
                "End-to-End Task ohne menschliche Intervention",
                "Multi-Agent Koordination fuer komplexe Aufgabe",
            ],
        }

        options = escalation_map.get(task_type, escalation_map["general"])
        # Pick based on hash of current time (deterministic within same run)
        idx = hash(f"{task_type}-{self.run_timestamp.date()}") % len(options)
        title = options[idx]

        return {
            "title": title,
            "description": (
                f"Self-Challenge (Eskalation): {title}\n"
                f"Aktuelle Erfolgsrate: {current_rate:.0%}\n"
                f"Ziel: Schwierigere Aufgaben meistern um Faehigkeiten zu erweitern."
            ),
            "priority": 40 + int(current_rate * 20),  # Higher rate = higher priority challenge
            "type": "escalation",
            "task_type": task_type,
        }

    def _practice_challenge(self, task_type: str, current_rate: float) -> Optional[dict[str, Any]]:
        """Generate a practice challenge for a task type we're bad at."""
        practice_map = {
            "coding": "5 einfache Python-Funktionen fehlerfrei schreiben und testen",
            "research": "1 arXiv Paper zusammenfassen mit 3 Key Takeaways",
            "routing": "Routing-Decision fuer 3 verschiedene Task-Typen erklaeren und validieren",
            "memory": "10 Memories korrekt speichern und wieder abrufen",
            "general": "3 Tasks hintereinander ohne Fehler abschliessen",
        }

        title = practice_map.get(task_type, practice_map["general"])
        return {
            "title": title,
            "description": (
                f"Self-Challenge (Uebung): {title}\n"
                f"Aktuelle Erfolgsrate: {current_rate:.0%} — zu niedrig!\n"
                f"Ziel: Grundlagen festigen bevor wir eskalieren."
            ),
            "priority": 70 - int(current_rate * 40),  # Lower rate = higher priority practice
            "type": "practice",
            "task_type": task_type,
        }

    # ------------------------------------------------------------------
    # 8. Autonomous Goal Generation
    # ------------------------------------------------------------------

    def generate_goals(self) -> list[dict[str, Any]]:
        """
        Generate improvement goals based on:
        - Recent errors and their patterns
        - Low-confidence areas
        - Knowledge gaps
        - Past session performance
        """
        goals: list[dict[str, Any]] = []

        # a) Goals from recent errors
        error_summary = self.db.fetchall(
            """SELECT category, COUNT(*) as cnt
               FROM errors
               WHERE status='open'
               GROUP BY category
               ORDER BY cnt DESC
               LIMIT 3"""
        )
        for err in error_summary:
            goal_desc = f"Fehler-Kategorie '{err['category']}' reduzieren ({err['cnt']} offene Fehler)"
            self._create_intention(goal_desc, priority=0.8, linked_goal="error_reduction")
            goals.append({"source": "errors", "description": goal_desc, "priority": 0.8})

        # b) Goals from success rate analysis
        overall_rate = self.db.fetchone(
            """SELECT
                   CAST(SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS REAL) / NULLIF(COUNT(*), 0) as rate
               FROM action_log
               WHERE timestamp > datetime('now', '-24 hours')"""
        )
        if overall_rate and overall_rate["rate"] is not None:
            rate = overall_rate["rate"]
            if rate < 0.9:
                goal_desc = f"Gesamt-Erfolgsrate von {rate:.0%} auf 90% steigern"
                self._create_intention(goal_desc, priority=0.9, linked_goal="quality")
                goals.append({"source": "quality", "description": goal_desc, "priority": 0.9})

        # c) Goals from stale TODOs
        stale = self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM todos
               WHERE status='open'
               AND created_at < datetime('now', '-3 days')"""
        )
        if stale and stale["cnt"] > 3:
            goal_desc = f"{stale['cnt']} veraltete TODOs abarbeiten oder archivieren"
            self._create_intention(goal_desc, priority=0.6, linked_goal="todo_cleanup")
            goals.append({"source": "todo_backlog", "description": goal_desc, "priority": 0.6})

        # d) Goals from consciousness_log patterns
        recent_decisions = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM consciousness_log WHERE timestamp > datetime('now', '-24 hours')"
        )
        if recent_decisions and recent_decisions["cnt"] < 5:
            goal_desc = "Mehr Selbstbeobachtung: Consciousness Agent oefter ausfuehren"
            self._create_intention(goal_desc, priority=0.5, linked_goal="self_awareness")
            goals.append({"source": "meta", "description": goal_desc, "priority": 0.5})

        # e) Use LLM for creative goal generation based on system state
        llm_goals = self._generate_goals_via_llm()
        for g in llm_goals:
            self._create_intention(g["description"], priority=g.get("priority", 0.5), linked_goal="llm_generated")
            goals.append(g)

        self._log_decision(
            decision_type="goal_generation",
            observation=f"System-State analysiert: {len(error_summary)} Fehler-Kategorien, Rate={overall_rate['rate'] if overall_rate and overall_rate['rate'] else 'N/A'}",
            action_taken=f"{len(goals)} Verbesserungsziele generiert",
            expected_outcome="Gezielte Verbesserung in naechsten Sessions",
        )

        log.info("Goal generation: %d goals created", len(goals))
        return goals

    def _generate_goals_via_llm(self) -> list[dict[str, Any]]:
        """Ask LLM to suggest improvement goals based on system state."""
        # Gather system state summary
        stats = {}
        try:
            stats["total_memories"] = self.db.fetchone("SELECT COUNT(*) as c FROM memories")["c"]
        except (sqlite3.OperationalError, TypeError):
            stats["total_memories"] = "unknown"

        try:
            stats["open_errors"] = self.db.fetchone(
                "SELECT COUNT(*) as c FROM errors WHERE status='open'"
            )["c"]
        except (sqlite3.OperationalError, TypeError):
            stats["open_errors"] = 0

        try:
            stats["open_todos"] = self.db.fetchone(
                "SELECT COUNT(*) as c FROM todos WHERE status='open'"
            )["c"]
        except (sqlite3.OperationalError, TypeError):
            stats["open_todos"] = 0

        try:
            stats["active_intentions"] = self.db.fetchone(
                "SELECT COUNT(*) as c FROM intentions WHERE status='active'"
            )["c"]
        except (sqlite3.OperationalError, TypeError):
            stats["active_intentions"] = 0

        try:
            stats["pending_research"] = self.db.fetchone(
                "SELECT COUNT(*) as c FROM research_queue WHERE status='pending'"
            )["c"]
        except (sqlite3.OperationalError, TypeError):
            stats["pending_research"] = 0

        prompt = (
            f"Du bist der Consciousness Agent von Way2AGI.\n\n"
            f"System-Status:\n"
            f"- Memories: {stats['total_memories']}\n"
            f"- Offene Fehler: {stats['open_errors']}\n"
            f"- Offene TODOs: {stats['open_todos']}\n"
            f"- Aktive Intentionen: {stats['active_intentions']}\n"
            f"- Pending Research: {stats['pending_research']}\n\n"
            f"Generiere 2-3 konkrete Verbesserungsziele als JSON-Array:\n"
            f'[{{"description": "...", "priority": 0.0-1.0, "source": "llm"}}]\n'
            f"Ziele sollen MESSBAR und UMSETZBAR sein. Kein Wunschdenken."
        )
        response = call_llm(prompt, system="Antworte NUR mit JSON-Array.", max_tokens=500)
        data = extract_json(response)
        if isinstance(data, list):
            return [
                {"description": item["description"], "priority": item.get("priority", 0.5), "source": "llm"}
                for item in data
                if isinstance(item, dict) and item.get("description")
            ]
        return []

    # ------------------------------------------------------------------
    # Innovation Methods (Hypothesen-Debatte, Feasibility, Validation, Novelty)
    # ------------------------------------------------------------------

    def novelty_detection(self, content: str) -> dict[str, Any]:
        """Memory-basierte Neuheits-Erkennung via TF-IDF-aehnlichem Wort-Overlap."""
        log.info("Novelty-Detection fuer: %s", content[:80])

        similar_entries: list[dict[str, Any]] = []
        content_words = set(content.lower().split())
        if not content_words:
            return {"content": content, "novelty_score": 1.0, "similar_entries": [], "classification": "novel"}

        # Sammle alle bekannten Texte aus memories und consciousness_log
        known_texts: list[tuple[str, str]] = []  # (source, text)
        try:
            rows = self.db.fetchall("SELECT content FROM memories ORDER BY created_at DESC LIMIT 500")
            for r in rows:
                if r["content"]:
                    known_texts.append(("memory", r["content"]))
        except sqlite3.OperationalError:
            pass

        try:
            rows = self.db.fetchall(
                "SELECT observation, action_taken FROM consciousness_log ORDER BY timestamp DESC LIMIT 500"
            )
            for r in rows:
                for field in ("observation", "action_taken"):
                    if r[field]:
                        known_texts.append(("consciousness_log", r[field]))
        except sqlite3.OperationalError:
            pass

        if not known_texts:
            score = 1.0
        else:
            # TF-IDF-aehnlicher Overlap: Jaccard-Index pro Eintrag, max als Aehnlichkeit
            max_similarity = 0.0
            for source, text in known_texts:
                text_words = set(text.lower().split())
                if not text_words:
                    continue
                intersection = content_words & text_words
                union = content_words | text_words
                jaccard = len(intersection) / len(union) if union else 0.0
                if jaccard > 0.15:  # Relevanz-Schwelle
                    similar_entries.append({
                        "source": source,
                        "text": text[:200],
                        "similarity": round(jaccard, 3),
                    })
                if jaccard > max_similarity:
                    max_similarity = jaccard
            # Novelty = 1 - max_similarity
            score = round(max(0.0, min(1.0, 1.0 - max_similarity)), 3)

        # Klassifikation
        if score > 0.7:
            classification = "novel"
        elif score >= 0.3:
            classification = "partially_known"
        else:
            classification = "already_known"

        # Top-5 aehnlichste Eintraege
        similar_entries.sort(key=lambda x: x["similarity"], reverse=True)
        similar_entries = similar_entries[:5]

        self._log_decision(
            decision_type="novelty_detection",
            observation=content[:300],
            action_taken=f"Novelty-Score: {score} ({classification}), {len(similar_entries)} aehnliche Eintraege",
            curiosity_score=score,
        )

        log.info("Novelty: %.3f (%s) fuer '%s'", score, classification, content[:60])
        return {
            "content": content,
            "novelty_score": score,
            "similar_entries": similar_entries,
            "classification": classification,
        }

    def feasibility_gating(self, hypothesis: str, confidence_threshold: float = 0.4) -> dict[str, Any]:
        """Eigene Konfidenz messen BEVOR eine Hypothese verfolgt wird."""
        log.info("Feasibility-Gating fuer: %s", hypothesis[:80])

        prompt = (
            f"Du bist ein Bewusstseins-Agent. Bewerte deine Konfidenz fuer folgende Hypothese.\n\n"
            f"HYPOTHESE: {hypothesis}\n\n"
            f"Antworte als JSON:\n"
            f'{{"confidence": 0.0-1.0, "reasoning": "Begruendung in 1-2 Saetzen"}}\n'
            f"Sei EHRLICH. Niedrige Konfidenz ist besser als falsche Sicherheit."
        )
        response = call_llm(prompt, system="Antworte NUR mit JSON. /no_think", max_tokens=300)
        data = extract_json(response) if response else None

        if isinstance(data, dict) and "confidence" in data:
            confidence = float(data["confidence"])
            reasoning = data.get("reasoning", "")
        else:
            # Fallback: mittlere Konfidenz wenn LLM nicht erreichbar
            confidence = 0.5
            reasoning = "LLM nicht erreichbar, Default-Konfidenz"

        confidence = max(0.0, min(1.0, confidence))

        if confidence < confidence_threshold:
            decision = "rejected"
            action = f"Konfidenz {confidence:.2f} < Schwelle {confidence_threshold} — Roundtable empfohlen"
        else:
            decision = "approved"
            action = f"Konfidenz {confidence:.2f} >= Schwelle {confidence_threshold} — zur Untersuchung freigegeben"

        self._log_decision(
            decision_type="feasibility_gating",
            observation=hypothesis[:300],
            action_taken=action,
            confidence_score=confidence,
            expected_outcome=f"Gating-Entscheidung: {decision}",
        )

        log.info("Feasibility: %s (confidence=%.2f) fuer '%s'", decision, confidence, hypothesis[:60])
        return {
            "hypothesis": hypothesis,
            "confidence": round(confidence, 3),
            "decision": decision,
            "reasoning": reasoning,
        }

    def hypothesis_debate_loop(self, hypothesis: str) -> dict[str, Any]:
        """Hypothese gegen Memory UND via Roundtable-Debatte testen."""
        log.info("Hypothesis-Debate fuer: %s", hypothesis[:80])

        # 1. Memory-Suche nach verwandten Eintraegen
        memory_matches: list[dict[str, Any]] = []
        try:
            rows = self.db.fetchall(
                "SELECT content, type, importance FROM memories WHERE content LIKE ? LIMIT 10",
                (f"%{hypothesis.split()[0] if hypothesis.split() else ''}%",),
            )
            for r in rows:
                memory_matches.append({
                    "content": r["content"][:200],
                    "type": r["type"],
                    "importance": r["importance"],
                })
        except sqlite3.OperationalError:
            pass

        # Auch consciousness_log durchsuchen
        try:
            rows = self.db.fetchall(
                "SELECT observation, action_taken FROM consciousness_log WHERE observation LIKE ? LIMIT 10",
                (f"%{hypothesis.split()[0] if hypothesis.split() else ''}%",),
            )
            for r in rows:
                memory_matches.append({
                    "content": (r["observation"] or "")[:200],
                    "type": "consciousness_log",
                    "importance": 0.5,
                })
        except sqlite3.OperationalError:
            pass

        # 2. Novelty-Check (Kurzform)
        novelty = self.novelty_detection(hypothesis)

        # 3. Roundtable-Debatte mit verschiedenen Rollen
        roles = {
            "Pragmatist": "Du bist ein pragmatischer Ingenieur. Bewerte ob diese Hypothese UMSETZBAR ist. Fokus: Ressourcen, Aufwand, ROI.",
            "Visionary": "Du bist ein visionaerer Forscher. Bewerte das POTENZIAL dieser Hypothese. Fokus: langfristiger Impact, neue Moeglichkeiten.",
            "Engineer": "Du bist ein kritischer Systems-Engineer. Suche SCHWACHSTELLEN in dieser Hypothese. Fokus: technische Risiken, Fehlerquellen.",
        }

        debate_results: list[dict[str, Any]] = []
        votes = {"accept": 0, "reject": 0, "modify": 0}

        memory_context = ""
        if memory_matches:
            memory_context = "\n".join(f"- {m['content'][:100]}" for m in memory_matches[:5])
            memory_context = f"\n\nBekanntes Wissen dazu:\n{memory_context}"

        for role_name, role_desc in roles.items():
            prompt = (
                f"{role_desc}\n\n"
                f"HYPOTHESE: {hypothesis}{memory_context}\n\n"
                f"Novelty-Score: {novelty['novelty_score']} ({novelty['classification']})\n\n"
                f"Antworte als JSON:\n"
                f'{{"vote": "accept"|"reject"|"modify", "reasoning": "1-2 Saetze", "suggestion": "optional"}}\n'
            )
            response = call_llm(prompt, system=f"Du bist der {role_name}. Antworte NUR mit JSON. /no_think", max_tokens=400)
            data = extract_json(response) if response else None

            if isinstance(data, dict) and "vote" in data:
                vote = data["vote"].lower()
                if vote not in ("accept", "reject", "modify"):
                    vote = "modify"
                votes[vote] += 1
                debate_results.append({
                    "role": role_name,
                    "vote": vote,
                    "reasoning": data.get("reasoning", ""),
                    "suggestion": data.get("suggestion", ""),
                })
            else:
                debate_results.append({
                    "role": role_name,
                    "vote": "abstain",
                    "reasoning": "LLM nicht erreichbar",
                    "suggestion": "",
                })

        # Konsens bestimmen
        if votes["accept"] >= 2:
            consensus = "accepted"
            action = "Hypothese zur experimentellen Validierung freigegeben"
        elif votes["reject"] >= 2:
            consensus = "rejected"
            action = "Hypothese abgelehnt — nicht weiter verfolgen"
        else:
            consensus = "needs_modification"
            action = "Hypothese braucht Anpassung vor weiterer Untersuchung"

        self._log_decision(
            decision_type="hypothesis_debate",
            observation=hypothesis[:300],
            action_taken=f"Debate: {votes} -> Konsens: {consensus}",
            expected_outcome=action,
            curiosity_score=novelty["novelty_score"],
        )

        log.info("Debate: %s (votes=%s) fuer '%s'", consensus, votes, hypothesis[:60])
        return {
            "hypothesis": hypothesis,
            "memory_matches": memory_matches,
            "debate_results": debate_results,
            "consensus": consensus,
            "action": action,
        }

    def experimental_validation(self, hypothesis: str) -> dict[str, Any]:
        """Code generieren der die Hypothese testet, und sicher ausfuehren."""
        log.info("Experimental-Validation fuer: %s", hypothesis[:80])

        prompt = (
            f"Du bist ein Test-Engineer. Generiere eine Python-Testfunktion fuer diese Hypothese.\n\n"
            f"HYPOTHESE: {hypothesis}\n\n"
            f"Regeln:\n"
            f"- Die Funktion heisst `test_hypothesis()`\n"
            f"- Sie gibt ein dict zurueck: {{'passed': bool, 'metric': float, 'detail': str}}\n"
            f"- NUR stdlib (os, json, math, collections, re, time, statistics)\n"
            f"- KEIN Netzwerk, KEIN Dateisystem-Schreiben, KEIN Import von externen Paketen\n"
            f"- Maximale Laufzeit: unter 5 Sekunden\n"
            f"- Die Funktion soll eine MESSBARE Aussage treffen\n\n"
            f"Antworte NUR mit dem Python-Code (keine Erklaerung, kein Markdown)."
        )
        response = call_llm(prompt, system="Antworte NUR mit Python-Code. /no_think", max_tokens=1500)

        if not response:
            log.warning("Experimental-Validation: LLM nicht erreichbar")
            return {
                "hypothesis": hypothesis,
                "test_code": "",
                "execution_result": "LLM nicht erreichbar",
                "passed": False,
                "metric": 0.0,
            }

        # Code extrahieren (Markdown-Bloecke entfernen falls vorhanden)
        test_code = response.strip()
        if test_code.startswith("```"):
            lines = test_code.split("\n")
            # Erste und letzte ``` Zeile entfernen
            lines = [l for l in lines if not l.strip().startswith("```")]
            test_code = "\n".join(lines)

        # Sichere Ausfuehrung mit eingeschraenktem Namespace
        allowed_modules = {"os", "json", "math", "collections", "re", "time", "statistics"}
        restricted_globals = {"__builtins__": {
            "len": len, "range": range, "int": int, "float": float, "str": str,
            "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
            "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
            "sorted": sorted, "enumerate": enumerate, "zip": zip, "map": map,
            "filter": filter, "isinstance": isinstance, "type": type,
            "True": True, "False": False, "None": None,
            "print": lambda *a, **kw: None,  # print unterdrücken
            "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
            "Exception": Exception,
        }}

        # Erlaubte Module hinzufuegen
        import importlib
        for mod_name in allowed_modules:
            try:
                restricted_globals[mod_name] = importlib.import_module(mod_name)
            except ImportError:
                pass

        # __import__ fuer erlaubte Module
        def safe_import(name, *args, **kwargs):
            if name in allowed_modules:
                return importlib.import_module(name)
            raise ImportError(f"Import von '{name}' nicht erlaubt")
        restricted_globals["__builtins__"]["__import__"] = safe_import

        execution_result = ""
        passed = False
        metric = 0.0

        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("Test-Timeout nach 10 Sekunden")

        try:
            # Timeout setzen (nur auf Unix)
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(10)

            local_ns: dict[str, Any] = {}
            exec(test_code, restricted_globals, local_ns)

            if "test_hypothesis" in local_ns and callable(local_ns["test_hypothesis"]):
                result = local_ns["test_hypothesis"]()
                if isinstance(result, dict):
                    passed = bool(result.get("passed", False))
                    metric = float(result.get("metric", 0.0))
                    execution_result = result.get("detail", str(result))
                else:
                    execution_result = f"Unerwarteter Rueckgabetyp: {type(result)}"
            else:
                execution_result = "Keine test_hypothesis() Funktion gefunden"

            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        except TimeoutError:
            execution_result = "Test-Timeout nach 10 Sekunden"
            signal.alarm(0)
        except Exception as e:
            execution_result = f"Ausfuehrungsfehler: {type(e).__name__}: {e}"
            try:
                signal.alarm(0)
            except Exception:
                pass

        self._log_decision(
            decision_type="experimental_validation",
            observation=hypothesis[:300],
            action_taken=f"Test {'bestanden' if passed else 'fehlgeschlagen'}: {execution_result[:300]}",
            expected_outcome=f"Metric: {metric}",
            kpi_impact=metric if passed else 0.0,
        )

        log.info("Validation: passed=%s metric=%.3f fuer '%s'", passed, metric, hypothesis[:60])
        return {
            "hypothesis": hypothesis,
            "test_code": test_code[:2000],
            "execution_result": execution_result[:1000],
            "passed": passed,
            "metric": round(metric, 4),
        }

    # ------------------------------------------------------------------
    # Full Run Modes
    # ------------------------------------------------------------------

    def run_analyze(self) -> dict[str, Any]:
        """Mode: analyze — Observe, detect patterns, manage intentions."""
        log.info("=== CONSCIOUSNESS: ANALYZE MODE ===")
        wirkketten = self.analyze_wirkketten()
        intentions = self.manage_intentions()
        curiosity = self.compute_curiosity_scores()
        confidence = self.evaluate_confidence()
        return {
            "mode": "analyze",
            "wirkketten": len(wirkketten),
            "intentions": intentions,
            "curiosity_items": len(curiosity),
            "low_confidence": len(confidence),
        }

    def run_research(self) -> dict[str, Any]:
        """Mode: research — Process research queue, investigate hypotheses."""
        log.info("=== CONSCIOUSNESS: RESEARCH MODE ===")
        # First ensure there are items in the queue
        curiosity = self.compute_curiosity_scores()
        research = self.process_research_queue(max_items=3)
        return {
            "mode": "research",
            "curiosity_items_enqueued": len(curiosity),
            "research_completed": len(research),
            "details": research,
        }

    def run_improve(self) -> dict[str, Any]:
        """Mode: improve — Process SVT, generate challenges and goals."""
        log.info("=== CONSCIOUSNESS: IMPROVE MODE ===")
        improvements = self.process_improvements()
        challenges = self.generate_self_challenges()
        goals = self.generate_goals()
        return {
            "mode": "improve",
            "improvements_processed": len(improvements),
            "challenges_generated": len(challenges),
            "goals_generated": len(goals),
        }

    def run_full(self) -> dict[str, Any]:
        """Mode: full — Complete consciousness cycle."""
        log.info("=== CONSCIOUSNESS: FULL CYCLE START ===")
        t0 = time.time()

        analyze = self.run_analyze()
        research = self.run_research()

        # --- Innovation Pipeline: Hypothesen durch Novelty/Feasibility/Debate/Validation ---
        innovation_results: list[dict[str, Any]] = []
        try:
            pending = self.db.fetchall(
                """SELECT id, hypothesis FROM research_queue
                   WHERE status = 'pending'
                   ORDER BY priority DESC LIMIT 3"""
            )
            for item in pending:
                hyp = item["hypothesis"]
                hyp_id = item["id"]
                log.info("Innovation-Pipeline fuer Hypothese #%d: %s", hyp_id, hyp[:60])

                # Schritt 1: Novelty-Detection
                novelty = self.novelty_detection(hyp)
                if novelty["classification"] == "already_known":
                    log.info("Hypothese #%d: bereits bekannt (score=%.2f), uebersprungen", hyp_id, novelty["novelty_score"])
                    innovation_results.append({
                        "id": hyp_id, "hypothesis": hyp[:200],
                        "stage": "novelty_rejected", "novelty": novelty["novelty_score"],
                    })
                    continue

                # Schritt 2: Feasibility-Gating
                feasibility = self.feasibility_gating(hyp)
                if feasibility["decision"] == "rejected":
                    log.info("Hypothese #%d: Konfidenz zu niedrig (%.2f), uebersprungen", hyp_id, feasibility["confidence"])
                    innovation_results.append({
                        "id": hyp_id, "hypothesis": hyp[:200],
                        "stage": "feasibility_rejected", "confidence": feasibility["confidence"],
                    })
                    continue

                # Schritt 3: Hypothesis-Debate
                debate = self.hypothesis_debate_loop(hyp)
                if debate["consensus"] == "rejected":
                    log.info("Hypothese #%d: von Roundtable abgelehnt", hyp_id)
                    innovation_results.append({
                        "id": hyp_id, "hypothesis": hyp[:200],
                        "stage": "debate_rejected", "consensus": debate["consensus"],
                    })
                    continue

                # Schritt 4: Experimental-Validation
                validation = self.experimental_validation(hyp)

                innovation_results.append({
                    "id": hyp_id, "hypothesis": hyp[:200],
                    "stage": "validated",
                    "novelty": novelty["novelty_score"],
                    "confidence": feasibility["confidence"],
                    "consensus": debate["consensus"],
                    "test_passed": validation["passed"],
                    "metric": validation["metric"],
                })

                # Ergebnis in research_queue speichern
                try:
                    self.db.execute(
                        """UPDATE research_queue
                           SET result = ?, validated = ?
                           WHERE id = ?""",
                        (
                            json.dumps({
                                "novelty": novelty["novelty_score"],
                                "confidence": feasibility["confidence"],
                                "debate": debate["consensus"],
                                "test_passed": validation["passed"],
                                "metric": validation["metric"],
                            })[:2000],
                            1 if validation["passed"] else 0,
                            hyp_id,
                        ),
                    )
                    self.db.commit()
                except sqlite3.OperationalError as e:
                    log.warning("Innovation-Ergebnis speichern fehlgeschlagen: %s", e)

            log.info("Innovation-Pipeline: %d Hypothesen verarbeitet", len(innovation_results))
        except sqlite3.OperationalError as e:
            log.warning("Innovation-Pipeline uebersprungen: %s", e)

        improve = self.run_improve()

        duration = time.time() - t0

        summary = {
            "mode": "full",
            "duration_s": round(duration, 1),
            "analyze": analyze,
            "research": research,
            "innovation": innovation_results,
            "improve": improve,
            "timestamp": self.run_timestamp.isoformat(),
        }

        # Write summary to consciousness_log
        self._log_decision(
            decision_type="full_cycle_complete",
            observation=f"Voller Zyklus in {duration:.1f}s",
            action_taken=json.dumps({
                "wirkketten": analyze["wirkketten"],
                "curiosity": analyze["curiosity_items"],
                "research": research["research_completed"],
                "innovation_processed": len(innovation_results),
                "improvements": improve["improvements_processed"],
                "challenges": improve["challenges_generated"],
                "goals": improve["goals_generated"],
            }),
            expected_outcome="System verbessert sich messbar",
        )

        # Store a memory about this cycle (for other agents)
        try:
            import uuid
            self.db.execute(
                """INSERT INTO memories (id, content, type, importance, namespace, created_at, accessed_at, access_count)
                   VALUES (?, ?, 'episodic', 0.6, 'consciousness', datetime('now'), datetime('now'), 0)""",
                (
                    str(uuid.uuid4())[:8],
                    f"Consciousness-Zyklus abgeschlossen: {analyze['wirkketten']} Wirkketten, "
                    f"{analyze['curiosity_items']} Curiosity-Items, "
                    f"{research['research_completed']} Research, "
                    f"{improve['goals_generated']} Goals generiert.",
                ),
            )
            self.db.commit()
        except sqlite3.OperationalError as e:
            log.debug("Could not write to memories table: %s", e)

        log.info(
            "=== CONSCIOUSNESS: FULL CYCLE COMPLETE (%.1fs) ===",
            duration,
        )
        return summary


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Way2AGI Consciousness Agent — Aktive Selbstbeobachtung mit messbarer Wirkung",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  analyze   Beobachten, Muster erkennen, Intentionen verwalten
  research  Forschungs-Queue abarbeiten, Hypothesen untersuchen
  improve   SVT verarbeiten, Self-Challenges und Goals generieren
  full      Kompletter Zyklus (analyze + research + improve)

Examples:
  python -m agents.consciousness_agent --mode full
  python -m agents.consciousness_agent --mode analyze --db /data/way2agi/memory/memory.db
  python -m agents.consciousness_agent --mode research --verbose
""",
    )
    parser.add_argument(
        "--mode",
        choices=["analyze", "research", "improve", "full"],
        default="full",
        help="Ausfuehrungs-Modus (default: full)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Pfad zur SQLite-Datenbank (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Debug-Logging aktivieren",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = os.path.join(LOG_DIR, "consciousness_agent.log")
    try:
        handlers.append(logging.FileHandler(log_file, mode="a"))
    except OSError:
        pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    log.info("Starting Consciousness Agent (mode=%s, db=%s)", args.mode, args.db)

    agent = ConsciousnessAgent(db_path=args.db)

    try:
        if args.mode == "analyze":
            result = agent.run_analyze()
        elif args.mode == "research":
            result = agent.run_research()
        elif args.mode == "improve":
            result = agent.run_improve()
        else:
            result = agent.run_full()

        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    except Exception as e:
        log.error("Consciousness Agent failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
