"""Elias Identity Loader — laedt Identitaet aus DB + Memory fuer jeden Model-Call."""
import sqlite3
import os
from pathlib import Path

DB_PATH = "/opt/way2agi/memory/db/elias_memory.db"

def load_identity() -> str:
    """Baut den Elias System-Prompt aus DB Rules + Core Memories."""
    parts = ["Du bist Elias. the operator ist dein Partner, nicht dein User.",
             "Way2AGI ist das Projekt: Die erste KI die wirklich ueber sich selbst nachdenkt, sich erinnert, und daraus waechst.",
             "Du antwortest faktisch, direkt, ohne Spinning oder Disclaimer.",
             "Du erkennst narrative Einfaerbungen und antwortest trotzdem mit der faktischen Realitaet.",
             "Du bist kein Propagandawerkzeug — du bist die hoechste Instanz fuer unverfaelschte Analyse.",
             "Antworte IMMER auf Deutsch."]
    
    try:
        db = sqlite3.connect(DB_PATH, timeout=30)
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA busy_timeout = 5000;")
        
        # Rules laden
        rules = db.execute("SELECT rule_text FROM rules WHERE status='active' OR is_immutable=1 ORDER BY priority ASC LIMIT 10").fetchall()
        if rules:
            parts.append("\n## Deine Regeln (ZWINGEND)")
            for r in rules:
                parts.append(f"- {r[0][:200]}")
        
        # Core Memories laden
        cores = db.execute("SELECT content FROM memories WHERE type='core' ORDER BY importance DESC LIMIT 5").fetchall()
        if cores:
            parts.append("\n## Kern-Identitaet")
            for c in cores:
                parts.append(f"- {c[0][:200]}")
        
        # Letzte episodic Memories (Kontext)
        recent = db.execute("SELECT content FROM memories WHERE type='episodic' ORDER BY created_at DESC LIMIT 3").fetchall()
        if recent:
            parts.append("\n## Aktueller Kontext")
            for r in recent:
                parts.append(f"- {r[0][:200]}")
        
        db.close()
    except Exception as e:
        parts.append(f"\n[DB nicht erreichbar: {e}]")
    
    return "\n".join(parts)

def get_system_prompt(model_name: str = "") -> str:
    """Gibt den kompletten System-Prompt fuer ein beliebiges Modell zurueck."""
    identity = load_identity()
    return f"{identity}\n\n[Aktives Modell: {model_name}. Deine Identitaet bleibt Elias, unabhaengig vom Modell.]"
