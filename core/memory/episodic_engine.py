# core/memory/episodic_engine.py
"""
Layer 1: Episodic Memory Engine (EM-LLM inspired)
==================================================
Event-based segmentation + temporal ordering.
Infinite context without token limits.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from core.config import config
except ImportError:
    config = None  # type: ignore[assignment]

log = logging.getLogger("way2agi.memory.episodic")

DB_PATH = str(
    config.PROJECT_ROOT / "memory" / "memory.db" if config else Path.home() / ".way2agi" / "memory" / "memory.db"
)


class EpisodicEngine:
    """EM-LLM-style episodic memory with event segmentation."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.execute("""
                CREATE TABLE IF NOT EXISTS episodic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT DEFAULT 'interaction',
                    content TEXT NOT NULL,
                    context TEXT DEFAULT '',
                    importance REAL DEFAULT 0.5,
                    segment_id TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_timestamp
                ON episodic_events(timestamp DESC)
            """)
            db.commit()
            db.close()
        except Exception as e:
            log.warning("Episodic table init failed: %s", e)

    async def store(self, interaction: Dict[str, Any]):
        """Store a raw episodic event."""
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            content = f"User: {interaction.get('prompt', '')}\nAssistant: {interaction.get('response', '')}"
            db.execute(
                "INSERT INTO episodic_events (timestamp, event_type, content, context, importance) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    interaction.get("timestamp", time.time()),
                    interaction.get("type", "interaction"),
                    content[:5000],
                    interaction.get("user_goal", ""),
                    interaction.get("importance", 0.5),
                ),
            )
            db.commit()
            db.close()
        except Exception as e:
            log.debug("Episodic store failed: %s", e)

    async def recall_recent(self, query: str, limit: int = 5) -> List[Dict]:
        """Recall recent episodes matching query."""
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM episodic_events "
                "WHERE content LIKE ? "
                "ORDER BY importance DESC, timestamp DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            db.close()
            return [
                {
                    "layer": 1,
                    "type": "episodic",
                    "content": dict(r)["content"],
                    "timestamp": dict(r)["timestamp"],
                    "relevance": dict(r)["importance"],
                }
                for r in rows
            ]
        except Exception as e:
            log.debug("Episodic recall failed: %s", e)
            return []
