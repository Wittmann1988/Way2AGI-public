"""
Titans Memory with Cognitive Replay — Infinite + Conscious Memory.
=================================================================

Basiert auf Titans Paper + "AI Meets Brain" (arXiv Feb/Maerz 2026):
- Erweitert 4-Layer-Memory mit cognitive neuroscience Prinzipien
- Continual Learning + Experience Replay (wie im Schlaf)
- Macht Memory "infinite" durch intelligente Konsolidierung

Mechanismen:
1. Surprise-based Encoding: Nur unerwartete Infos werden gespeichert
2. Sleep-like Replay: Periodische Konsolidierung (wie menschlicher Schlaf)
3. Forgetting Curve: Exponentieller Decay mit Reactivation
4. Cross-Memory Integration: Verbindungen zwischen Memory-Tiers

Integration:
- Erweitert memory/src/server.py
- Nutzt elias-memory Backend
- Kompatibel mit consciousness_agent.py

Usage:
    from memory.titans_replay import TitansMemory
    tm = TitansMemory(db_path="/data/elias-memory/memory.db")
    await tm.encode("Neue Erkenntnis", surprise=0.8)
    await tm.sleep_replay()  # Konsolidierung
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

log = logging.getLogger("way2agi.titans_memory")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SURPRISE_THRESHOLD = 0.4        # Minimum surprise for encoding
DECAY_RATE = 0.05               # Forgetting curve lambda
REPLAY_BATCH_SIZE = 20          # Memories per replay cycle
CONSOLIDATION_THRESHOLD = 0.3   # Below this -> consolidate or forget
REACTIVATION_BOOST = 0.3        # Strength boost on retrieval
MAX_WORKING_MEMORY = 7          # Miller's magic number


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TitansRecord:
    """Ein Memory-Record mit Titans-Erweiterungen."""
    id: Optional[int] = None
    content: str = ""
    memory_type: str = "episodic"  # episodic | semantic | procedural | buffer
    surprise: float = 0.5
    strength: float = 1.0
    access_count: int = 0
    last_accessed: Optional[str] = None
    connections: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ReplayResult:
    """Ergebnis eines Sleep-Replay-Zyklus."""
    consolidated: int = 0
    forgotten: int = 0
    strengthened: int = 0
    new_connections: int = 0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Titans Memory System
# ---------------------------------------------------------------------------

class TitansMemory:
    """
    Erweiterte Memory mit Cognitive Replay.

    Features:
    - Surprise-based Encoding
    - Exponential Forgetting Curve
    - Sleep-like Replay/Consolidation
    - Cross-Memory Connections
    - Working Memory with capacity limit
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS titans_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        memory_type TEXT DEFAULT 'episodic',
        surprise REAL DEFAULT 0.5,
        strength REAL DEFAULT 1.0,
        access_count INTEGER DEFAULT 0,
        last_accessed TEXT,
        connections TEXT DEFAULT '[]',
        metadata TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now')),
        consolidated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS titans_replay_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consolidated INTEGER DEFAULT 0,
        forgotten INTEGER DEFAULT 0,
        strengthened INTEGER DEFAULT 0,
        new_connections INTEGER DEFAULT 0,
        duration_ms REAL DEFAULT 0.0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_titans_type ON titans_memories(memory_type);
    CREATE INDEX IF NOT EXISTS idx_titans_strength ON titans_memories(strength DESC);
    CREATE INDEX IF NOT EXISTS idx_titans_surprise ON titans_memories(surprise DESC);
    """

    def __init__(self, db_path: str = "/data/elias-memory/memory.db") -> None:
        self.db_path = db_path
        self._working_memory: list[TitansRecord] = []
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    # --- Encoding ---

    def encode(self, content: str, memory_type: str = "episodic",
               surprise: float = 0.5, metadata: Optional[dict] = None) -> Optional[int]:
        """
        Encodiere neue Information.
        Nur wenn Surprise > Threshold wird gespeichert.
        """
        if surprise < SURPRISE_THRESHOLD:
            log.debug("Titans: Skipping low-surprise memory (%.2f < %.2f)", surprise, SURPRISE_THRESHOLD)
            return None

        # Strength proportional to surprise
        strength = min(1.0, 0.5 + surprise * 0.5)

        record = TitansRecord(
            content=content,
            memory_type=memory_type,
            surprise=surprise,
            strength=strength,
            metadata=metadata or {},
        )

        record_id = self._store(record)

        # Update working memory
        self._working_memory.append(record)
        if len(self._working_memory) > MAX_WORKING_MEMORY:
            # Evict lowest-strength item
            self._working_memory.sort(key=lambda r: r.strength, reverse=True)
            evicted = self._working_memory.pop()
            log.debug("Titans: Evicted from working memory: %s", evicted.content[:50])

        log.info("Titans encode: id=%d surprise=%.2f strength=%.2f type=%s",
                 record_id, surprise, strength, memory_type)
        return record_id

    def _store(self, record: TitansRecord) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO titans_memories (content, memory_type, surprise, strength, "
                "access_count, connections, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.content, record.memory_type, record.surprise, record.strength,
                 record.access_count, json.dumps(record.connections),
                 json.dumps(record.metadata)),
            )
            record.id = cursor.lastrowid
            return cursor.lastrowid

    # --- Retrieval ---

    def retrieve(self, query: str, memory_type: Optional[str] = None,
                 limit: int = 5) -> list[TitansRecord]:
        """
        Rufe Memories ab. Aktualisiert Strength (Reactivation).
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if memory_type:
                rows = conn.execute(
                    "SELECT * FROM titans_memories WHERE memory_type = ? AND strength > ? "
                    "AND content LIKE ? ORDER BY strength DESC LIMIT ?",
                    (memory_type, CONSOLIDATION_THRESHOLD * 0.5, f"%{query}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM titans_memories WHERE strength > ? "
                    "AND content LIKE ? ORDER BY strength DESC LIMIT ?",
                    (CONSOLIDATION_THRESHOLD * 0.5, f"%{query}%", limit),
                ).fetchall()

            records = []
            for row in rows:
                record = TitansRecord(
                    id=row["id"],
                    content=row["content"],
                    memory_type=row["memory_type"],
                    surprise=row["surprise"],
                    strength=row["strength"],
                    access_count=row["access_count"],
                    connections=json.loads(row["connections"]),
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                )
                records.append(record)

                # Reactivation: boost strength on access
                new_strength = min(1.0, record.strength + REACTIVATION_BOOST)
                conn.execute(
                    "UPDATE titans_memories SET strength = ?, access_count = access_count + 1, "
                    "last_accessed = datetime('now') WHERE id = ?",
                    (new_strength, record.id),
                )

            return records

    # --- Forgetting Curve ---

    def apply_decay(self) -> int:
        """
        Wende exponentiellen Decay auf alle Memories an.
        S(t) = S(0) * e^(-lambda * t)
        t = Stunden seit letztem Zugriff
        """
        now = datetime.now()
        decayed = 0

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, strength, last_accessed, created_at FROM titans_memories "
                "WHERE strength > 0.01"
            ).fetchall()

            for row in rows:
                last = row["last_accessed"] or row["created_at"]
                try:
                    last_dt = datetime.fromisoformat(last)
                except (ValueError, TypeError):
                    continue

                hours = max(0, (now - last_dt).total_seconds() / 3600)
                new_strength = row["strength"] * math.exp(-DECAY_RATE * hours)
                new_strength = max(0.01, new_strength)

                if abs(new_strength - row["strength"]) > 0.001:
                    conn.execute(
                        "UPDATE titans_memories SET strength = ? WHERE id = ?",
                        (new_strength, row["id"]),
                    )
                    decayed += 1

        log.info("Titans decay: %d memories updated", decayed)
        return decayed

    # --- Sleep-like Replay ---

    def sleep_replay(self) -> ReplayResult:
        """
        Sleep-like Replay: Konsolidiere und staerke wichtige Memories.

        Ablauf:
        1. Decay anwenden
        2. Schwache Memories vergessen (< threshold)
        3. Starke Memories weiter staerken
        4. Verbindungen zwischen aehnlichen Memories erstellen
        """
        start = time.time()
        result = ReplayResult()

        # Step 1: Apply decay
        self.apply_decay()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Step 2: Forget very weak memories
            forgotten = conn.execute(
                "DELETE FROM titans_memories WHERE strength < ?",
                (CONSOLIDATION_THRESHOLD * 0.3,),
            ).rowcount
            result.forgotten = forgotten

            # Step 3: Get batch for replay
            batch = conn.execute(
                "SELECT * FROM titans_memories ORDER BY strength * surprise DESC LIMIT ?",
                (REPLAY_BATCH_SIZE,),
            ).fetchall()

            # Step 4: Strengthen high-value memories
            for row in batch:
                if row["surprise"] >= 0.6:
                    new_strength = min(1.0, row["strength"] + 0.1)
                    conn.execute(
                        "UPDATE titans_memories SET strength = ?, consolidated_at = datetime('now') WHERE id = ?",
                        (new_strength, row["id"]),
                    )
                    result.strengthened += 1

            # Step 5: Find and create connections between related memories
            for i, row_a in enumerate(batch):
                for row_b in batch[i + 1:]:
                    if row_a["memory_type"] == row_b["memory_type"]:
                        # Simple word overlap check
                        words_a = set(row_a["content"].lower().split())
                        words_b = set(row_b["content"].lower().split())
                        overlap = len(words_a & words_b)
                        if overlap >= 3:
                            # Add bidirectional connection
                            conns_a = json.loads(row_a["connections"])
                            conns_b = json.loads(row_b["connections"])
                            if row_b["id"] not in conns_a:
                                conns_a.append(row_b["id"])
                                conn.execute(
                                    "UPDATE titans_memories SET connections = ? WHERE id = ?",
                                    (json.dumps(conns_a), row_a["id"]),
                                )
                                result.new_connections += 1
                            if row_a["id"] not in conns_b:
                                conns_b.append(row_a["id"])
                                conn.execute(
                                    "UPDATE titans_memories SET connections = ? WHERE id = ?",
                                    (json.dumps(conns_b), row_b["id"]),
                                )
                                result.new_connections += 1

            # Step 6: Consolidate episodic -> semantic (frequent access)
            to_consolidate = conn.execute(
                "SELECT id FROM titans_memories WHERE memory_type = 'episodic' "
                "AND access_count >= 5 AND strength >= 0.7"
            ).fetchall()
            for row in to_consolidate:
                conn.execute(
                    "UPDATE titans_memories SET memory_type = 'semantic', "
                    "consolidated_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
                result.consolidated += 1

        result.duration_ms = (time.time() - start) * 1000

        # Log replay result
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO titans_replay_log (consolidated, forgotten, strengthened, "
                "new_connections, duration_ms) VALUES (?, ?, ?, ?, ?)",
                (result.consolidated, result.forgotten, result.strengthened,
                 result.new_connections, result.duration_ms),
            )

        log.info("Titans replay: consolidated=%d forgotten=%d strengthened=%d "
                 "connections=%d duration=%.0fms",
                 result.consolidated, result.forgotten, result.strengthened,
                 result.new_connections, result.duration_ms)
        return result

    # --- Stats ---

    def get_stats(self) -> dict[str, Any]:
        """Memory-Statistiken."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM titans_memories").fetchone()[0]
            by_type = conn.execute(
                "SELECT memory_type, COUNT(*), AVG(strength), AVG(surprise) "
                "FROM titans_memories GROUP BY memory_type"
            ).fetchall()
            replays = conn.execute(
                "SELECT COUNT(*), SUM(consolidated), SUM(forgotten) FROM titans_replay_log"
            ).fetchone()

            return {
                "total_memories": total,
                "working_memory_size": len(self._working_memory),
                "by_type": {
                    row[0]: {"count": row[1], "avg_strength": round(row[2], 3), "avg_surprise": round(row[3], 3)}
                    for row in by_type
                },
                "total_replays": replays[0] or 0,
                "total_consolidated": replays[1] or 0,
                "total_forgotten": replays[2] or 0,
            }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Way2AGI Titans Memory")
    parser.add_argument("--db", default="/data/elias-memory/memory.db")
    parser.add_argument("--encode", help="Encode new memory")
    parser.add_argument("--surprise", type=float, default=0.6)
    parser.add_argument("--retrieve", help="Retrieve memories matching query")
    parser.add_argument("--replay", action="store_true", help="Run sleep replay")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--decay", action="store_true", help="Apply decay")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    tm = TitansMemory(db_path=args.db)

    if args.encode:
        rec_id = tm.encode(args.encode, surprise=args.surprise)
        print(f"Encoded: id={rec_id}")
    elif args.retrieve:
        records = tm.retrieve(args.retrieve)
        for r in records:
            print(f"[{r.id}] strength={r.strength:.2f} surprise={r.surprise:.2f}: {r.content[:100]}")
    elif args.replay:
        result = tm.sleep_replay()
        print(f"Replay: consolidated={result.consolidated} forgotten={result.forgotten} "
              f"strengthened={result.strengthened} connections={result.new_connections}")
    elif args.stats:
        stats = tm.get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    elif args.decay:
        count = tm.apply_decay()
        print(f"Decayed: {count} memories")
    else:
        parser.print_help()
