#!/usr/bin/env python3
"""
Way2AGI Code Review Cronjob
Alle 3 Tage: Python-Dateien pruefen via Groq (llama-3.3-70b).
Ergebnisse als TODOs in Elias DB speichern.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path("/opt/way2agi/Way2AGI")
DB_PATH = os.environ.get("ELIAS_DB", "/opt/way2agi/memory/memory.db")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
MAX_FILE_CHARS = 6000
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "venv", ".venv"}


def get_db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS todos ("
        "id TEXT PRIMARY KEY, title TEXT, description TEXT, "
        "priority INTEGER DEFAULT 50, status TEXT DEFAULT 'open', "
        "created_at TEXT, completed_at TEXT)"
    )
    db.commit()
    return db


def collect_py_files(limit=0):
    files = []
    for p in sorted(REPO.rglob("*.py")):
        if any(s in p.parts for s in SKIP_DIRS):
            continue
        if p.stat().st_size < 50:
            continue
        files.append(p)
    if limit:
        files = files[:limit]
    return files


def review_file(filepath):
    code = filepath.read_text(errors="replace")[:MAX_FILE_CHARS]
    rel = filepath.relative_to(REPO)
    prompt = (
        f"Review diese Python-Datei '{rel}' auf:\n"
        f"1. Sicherheitsprobleme (hardcoded secrets, injection, unsichere imports)\n"
        f"2. Performance-Probleme (unnoetige Schleifen, fehlende Caches)\n"
        f"3. Code-Qualitaet (tote Imports, Duplikate, fehlende Error-Handling)\n"
        f'Antworte NUR mit JSON: {{"issues": [{{"severity": "high|medium|low", '
        f'"title": "kurz", "detail": "erklaerung"}}]}}\n'
        f'Wenn keine Probleme: {{"issues": []}}\n\n'
        f"```python\n{code}\n```"
    )
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.2,
    })
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", GROQ_URL,
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {GROQ_KEY}",
             "-d", payload],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        text = data["choices"][0]["message"]["content"]
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text), str(rel)
    except Exception as e:
        print(f"  FEHLER bei {rel}: {e}", file=sys.stderr)
        return None, str(rel)


def save_todos(db, issues, filepath):
    count = 0
    for issue in issues:
        sev = issue.get("severity", "medium")
        title = issue.get("title", "Unbekannt")
        detail = issue.get("detail", "")
        prio = {"high": 80, "medium": 50, "low": 20}.get(sev, 50)
        tid = f"CR{int(time.time()) % 100000:05d}"
        desc = f"[Code-Review {datetime.now():%Y-%m-%d}] {filepath}\n{detail}"
        try:
            db.execute(
                "INSERT OR IGNORE INTO todos (id, title, description, priority, "
                "status, created_at) VALUES (?, ?, ?, ?, 'open', datetime('now'))",
                (tid, f"[{sev.upper()}] {title}", desc, prio),
            )
            count += 1
            time.sleep(0.05)
        except Exception as e:
            print(f"  DB-Fehler: {e}", file=sys.stderr)
    if count:
        db.commit()
    return count


def main():
    if not GROQ_KEY:
        print("FEHLER: GROQ_API_KEY nicht gesetzt!", file=sys.stderr)
        sys.exit(1)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    files = collect_py_files(limit=limit)
    print(f"Code-Review Start: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Dateien: {len(files)}")

    db = get_db()
    total_issues = 0

    for f in files:
        rel = f.relative_to(REPO)
        print(f"  Pruefe {rel}...", end=" ", flush=True)
        result, fpath = review_file(f)
        if result is None:
            print("SKIP (Fehler)")
            continue
        issues = result.get("issues", [])
        if issues:
            saved = save_todos(db, issues, fpath)
            total_issues += saved
            print(f"{len(issues)} Issues ({saved} gespeichert)")
        else:
            print("OK")
        time.sleep(1)

    db.close()
    print(f"\nFertig: {total_issues} Issues in {len(files)} Dateien.")


if __name__ == "__main__":
    main()
