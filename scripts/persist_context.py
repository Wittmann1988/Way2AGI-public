#!/usr/bin/env python3
"""Persistiert Opus-Kontext ins episodic Memory Layer. Alle 15 Min via Cronjob."""
import json, os, sqlite3, glob, uuid
from datetime import datetime
from pathlib import Path

MEMORY_DB = "/opt/way2agi/memory/db/elias_memory.db"
OLLAMA_URL = "http://localhost:11434/api/generate"

def get_latest_session():
    pattern = str(Path.home() / ".claude/projects/*/*.jsonl")
    sessions = glob.glob(pattern)
    return max(sessions, key=os.path.getmtime) if sessions else None

def extract_messages(path, n=20):
    messages = []
    with open(path) as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("type") == "user" and not data.get("isMeta"):
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 10:
                        messages.append(("user", content[:500]))
                elif data.get("type") == "assistant":
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                messages.append(("assistant", c["text"][:500]))
                    elif isinstance(content, str) and len(content) > 10:
                        messages.append(("assistant", content[:500]))
            except:
                continue
    return messages[-n:]

def summarize(messages):
    import requests, os
    text = "\n".join(f"{role}: {content}" for role, content in messages)
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        # Fallback: lade aus .env
        try:
            with open("/opt/way2agi/.env") as f:
                for line in f:
                    if line.startswith("GROQ_API_KEY="):
                        api_key = line.strip().split("=", 1)[1].strip('"').strip("'")
        except: pass
    if not api_key:
        return "Kein GROQ_API_KEY"
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [
                {"role": "system", "content": "Fasse die Konversation in 3-5 Saetzen auf Deutsch zusammen. Fokus auf Entscheidungen und Ergebnisse."},
                {"role": "user", "content": text[:4000]}
            ], "max_tokens": 300}, timeout=15)
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Groq Fehler: {e}"

def save(summary):
    conn = sqlite3.connect(MEMORY_DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    now = datetime.now().isoformat()
    mem_id = f"ctx-{now[:19].replace(':', '').replace('-', '').replace('T', '-')}"
    conn.execute(
        "INSERT INTO memories (id, content, type, importance, created_at, accessed_at, access_count, metadata, namespace, scope, valence, salience) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mem_id, f"[SESSION-KONTEXT {now[:16]}] {summary}", "episodic", 0.8, now, now, 0, '{"source": "persist_context.py"}', "global", "shared", 0.2, 0.7)
    )
    conn.commit()
    conn.close()
    print(f"{now}: Kontext gespeichert ({len(summary)} Zeichen) [id={mem_id}]")

if __name__ == "__main__":
    session = get_latest_session()
    if not session:
        print("Keine Session gefunden")
        exit(0)
    print(f"Session: {session}")
    msgs = extract_messages(session)
    if not msgs:
        print("Keine Nachrichten")
        exit(0)
    print(f"{len(msgs)} Nachrichten extrahiert")
    summary = summarize(msgs)
    if summary:
        save(summary)
    else:
        print("Leere Zusammenfassung")
