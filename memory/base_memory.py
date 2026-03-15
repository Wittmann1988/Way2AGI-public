# memory/base_memory.py
"""
Way2AGI Base Memory — Gemeinsame Schnittstelle fuer alle Memory-Implementierungen.
==================================================================================

Stellt sicher dass alle Memory-Module:
- Einheitlich store/retrieve/forget anbieten
- An die SQLite DB angebunden sind
- Mit dem 6-Layer-System kompatibel sind

Usage:
    from memory.base_memory import BaseMemory
    class MyMemory(BaseMemory):
        def store(self, content, **kw): ...
        def retrieve(self, query, **kw): ...
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.base_memory")

DB_PATH = os.environ.get("WAY2AGI_DB", "/data/elias-memory/memory.db")


class BaseMemory:
    """
    Abstrakte Basis fuer alle Memory-Implementierungen.

    Subklassen muessen mindestens store() und retrieve() implementieren.
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path

    def store(self, content: str, memory_type: str = "episodic",
              importance: float = 0.5, metadata: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Speichere einen Memory-Eintrag. Gibt ID zurueck oder None."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT INTO memories (content, type, importance, namespace, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (content, memory_type, importance,
                     (metadata or {}).get("namespace", "default"),
                     datetime.now().isoformat()),
                )
                log.debug("BaseMemory store: id=%d type=%s", cursor.lastrowid, memory_type)
                return cursor.lastrowid
        except Exception as e:
            log.warning("BaseMemory store failed: %s", e)
            return None

    def retrieve(self, query: str, memory_type: Optional[str] = None,
                 limit: int = 5) -> List[Dict[str, Any]]:
        """Rufe Memories ab die zur Query passen."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                if memory_type:
                    rows = conn.execute(
                        "SELECT * FROM memories WHERE type = ? AND content LIKE ? "
                        "ORDER BY importance DESC LIMIT ?",
                        (memory_type, f"%{query}%", limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memories WHERE content LIKE ? "
                        "ORDER BY importance DESC LIMIT ?",
                        (f"%{query}%", limit),
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            log.warning("BaseMemory retrieve failed: %s", e)
            return []

    def forget(self, memory_id: int) -> bool:
        """Loesche einen Memory-Eintrag."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                return True
        except Exception as e:
            log.warning("BaseMemory forget failed: %s", e)
            return False

    def count(self, memory_type: Optional[str] = None) -> int:
        """Zaehle Memories."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if memory_type:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE type = ?", (memory_type,)
                    ).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                return row[0] if row else 0
        except Exception:
            return 0
