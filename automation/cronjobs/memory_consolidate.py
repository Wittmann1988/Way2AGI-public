#!/usr/bin/env python3
"""
Memory Consolidation Cronjob
=============================
Konsolidiert episodische Memories aelter als 24h zu Tages-Zusammenfassungen.
Nutzt Groq (llama-3.3-70b, kostenlos) via CURL (urllib wird von Cloudflare geblockt!).
Fuehrt WAL Checkpoint aus.

Cronjob: 0 5 * * * (taeglich 05:00)
"""

import sqlite3
import json
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = "/opt/way2agi/memory/memory.db"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def log(msg):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [consolidate] {msg}", flush=True)


def get_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL;")
    db.execute("PRAGMA busy_timeout = 10000;")
    db.row_factory = sqlite3.Row
    return db


def get_old_episodic_memories(db):
    """Holt alle episodic Memories aelter als 24h die noch nicht konsolidiert sind."""
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    rows = db.execute(
        "SELECT id, content, importance, created_at, tags, source "
        "FROM memories "
        "WHERE type = 'episodic' "
        "AND created_at < ? "
        "AND (tags IS NULL OR tags NOT LIKE '%consolidated%') "
        "ORDER BY created_at ASC",
        (cutoff,)
    ).fetchall()
    return rows


def group_by_day(memories):
    """Gruppiert Memories nach Datum."""
    days = defaultdict(list)
    for m in memories:
        day = m["created_at"][:10]
        days[day].append(m)
    return days


def summarize_with_groq(day, memories):
    """Nutzt Groq llama-3.3-70b via CURL (urllib wird von Cloudflare geblockt!)."""
    if not GROQ_API_KEY:
        log("FEHLER: GROQ_API_KEY nicht gesetzt!")
        return None

    entries = []
    for m in memories:
        entries.append(f"[{m['created_at']}] (importance={m['importance']}): {m['content'][:500]}")

    prompt = f"""Du bist ein Memory-Konsolidierungsagent fuer Way2AGI.
Hier sind {len(memories)} episodische Memory-Eintraege vom {day}.
Fasse sie zu EINER praegnanten Tages-Zusammenfassung zusammen.

Regeln:
- Deutsch
- Maximal 500 Woerter
- Wichtige Erkenntnisse, Fehler und Fortschritte hervorheben
- Technische Details beibehalten (Modellnamen, Ports, Fehler-Codes)
- Format: Stichpunkte, gruppiert nach Thema

Eintraege:
{chr(10).join(entries)}

Zusammenfassung fuer {day}:"""

    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1000,
    })

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", GROQ_URL,
             "-H", f"Authorization: Bearer {GROQ_API_KEY}",
             "-H", "Content-Type: application/json",
             "-d", payload,
             "--max-time", "60"],
            capture_output=True, text=True, timeout=70
        )
        if result.returncode != 0:
            log(f"curl Fehler: {result.stderr[:200]}")
            return None
        data = json.loads(result.stdout)
        if "error" in data:
            log(f"Groq API Fehler: {data['error']}")
            return None
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"Groq API Fehler: {e}")
        return None


def mark_as_consolidated(db, memory_ids):
    """Markiert Memories als konsolidiert (tags += 'consolidated')."""
    for mid in memory_ids:
        current_tags = db.execute(
            "SELECT tags FROM memories WHERE id = ?", (mid,)
        ).fetchone()["tags"]

        if current_tags:
            new_tags = current_tags + ",consolidated"
        else:
            new_tags = "consolidated"

        db.execute(
            "UPDATE memories SET tags = ? WHERE id = ?",
            (new_tags, mid)
        )
    db.commit()


def save_summary(db, day, summary, source_count):
    """Speichert die Tages-Zusammenfassung als semantic Memory."""
    summary_id = "consolidation-" + day
    content = f"Tages-Zusammenfassung {day} ({source_count} Eintraege konsolidiert):\n\n{summary}"

    db.execute(
        "INSERT OR REPLACE INTO memories (id, content, type, importance, namespace, tags, source, created_at, metadata) "
        "VALUES (?, ?, 'semantic', 0.8, 'consolidated', 'daily-summary,auto-consolidated', 'memory_consolidate', ?, ?)",
        (summary_id, content, f"{day}T05:00:00",
         json.dumps({"source_count": source_count, "consolidation_date": datetime.now().isoformat()}))
    )
    db.commit()


def wal_checkpoint(db):
    """Fuehrt WAL Checkpoint aus fuer Konsistenz."""
    try:
        result = db.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        log(f"WAL Checkpoint: busy={result[0]}, log={result[1]}, checkpointed={result[2]}")
    except Exception as e:
        log(f"WAL Checkpoint Fehler: {e}")


def check_db_integrity(db):
    """Prueft DB Integritaet."""
    result = db.execute("PRAGMA integrity_check;").fetchone()
    status = result[0] if result else "unknown"
    if status != "ok":
        log(f"WARNUNG: DB Integritaet: {status}")
    else:
        log("DB Integritaet: OK")
    return status == "ok"


def main():
    log("=== Memory Consolidation gestartet ===")

    db = get_db()

    # 1. DB Integritaet pruefen
    check_db_integrity(db)

    # 2. Alte episodic Memories holen
    memories = get_old_episodic_memories(db)
    log(f"{len(memories)} episodic Memories aelter als 24h gefunden")

    if not memories:
        log("Nichts zu konsolidieren.")
        wal_checkpoint(db)
        db.close()
        return

    # 3. Nach Tag gruppieren
    days = group_by_day(memories)
    log(f"{len(days)} Tage zu konsolidieren: {', '.join(sorted(days.keys()))}")

    # 4. Pro Tag zusammenfassen
    consolidated_total = 0
    for day in sorted(days.keys()):
        day_memories = days[day]
        log(f"Konsolidiere {day}: {len(day_memories)} Eintraege...")

        if len(day_memories) < 3:
            log(f"  Uebersprungen (weniger als 3 Eintraege)")
            continue

        summary = summarize_with_groq(day, day_memories)
        if summary:
            save_summary(db, day, summary, len(day_memories))
            memory_ids = [m["id"] for m in day_memories]
            mark_as_consolidated(db, memory_ids)
            consolidated_total += len(day_memories)
            log(f"  OK: {len(day_memories)} Eintraege -> 1 Zusammenfassung")
        else:
            log(f"  FEHLER: Zusammenfassung fehlgeschlagen")

        time.sleep(2)  # Rate Limit

    # 5. WAL Checkpoint
    wal_checkpoint(db)

    log(f"=== Fertig: {consolidated_total} Eintraege konsolidiert ===")
    db.close()


if __name__ == "__main__":
    main()
