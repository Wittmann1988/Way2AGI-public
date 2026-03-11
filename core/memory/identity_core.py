# core/memory/identity_core.py
"""
Layer 6: Identity Core (Immutable + Evolving)
==============================================
Schuetzt die Kern-Identitaet des Systems.
Evolving: Workflow-Modelle, Praeferenzen, Kommunikationsstil.
Immutable: Name, Werte, Grundregeln.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from core.config import config
except ImportError:
    config = None  # type: ignore[assignment]

log = logging.getLogger("way2agi.memory.identity")

DB_PATH = str(
    config.PROJECT_ROOT / "memory" / "memory.db" if config else Path.home() / ".way2agi" / "memory" / "memory.db"
)


class IdentityCore:
    """Manages the immutable + evolving identity of the system."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.execute("""
                CREATE TABLE IF NOT EXISTS identity_vault (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    immutable INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            db.commit()
            db.close()
        except Exception as e:
            log.warning("Identity table init failed: %s", e)

    async def load(self) -> Dict[str, Any]:
        """Load full identity from DB."""
        identity: Dict[str, Any] = {}
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT key, value, immutable FROM identity_vault").fetchall()
            db.close()
            for r in rows:
                identity[r["key"]] = {
                    "value": r["value"],
                    "immutable": bool(r["immutable"]),
                }
            log.info("Identity loaded: %d entries", len(identity))
        except Exception as e:
            log.warning("Identity load failed: %s", e)
        return identity

    async def update_from_interaction(self, interaction: Dict[str, Any]):
        """Update evolving identity traits from interaction patterns."""
        # Only update non-immutable traits
        # TODO: Detect communication style changes, preference shifts
        pass

    async def set(self, key: str, value: str, immutable: bool = False):
        """Set an identity value."""
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            # Don't overwrite immutable values
            existing = db.execute(
                "SELECT immutable FROM identity_vault WHERE key = ?", (key,)
            ).fetchone()
            if existing and existing[0] == 1:
                log.warning("Cannot overwrite immutable identity key: %s", key)
                db.close()
                return
            db.execute(
                "INSERT OR REPLACE INTO identity_vault (key, value, immutable, updated_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (key, value, 1 if immutable else 0),
            )
            db.commit()
            db.close()
        except Exception as e:
            log.warning("Identity set failed: %s", e)
