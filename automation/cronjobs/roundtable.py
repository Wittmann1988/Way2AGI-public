#!/usr/bin/env python3
"""
Auto-Roundtable Cronjob — Nimmt Research-Findings, fragt alle Modelle.
Laeuft 1x taeglich (12:00) nach Research (07:00).
NEU: Liest arXiv-Findings, erstellt konkrete TODOs aus Konsens.
"""

import json
import re
import urllib.request
import sqlite3
import datetime
import logging
import os
import sys
import uuid

DB_PATH = "/opt/way2agi/memory/db/elias_memory.db"
DB_FALLBACK = "/opt/way2agi/memory/memory.db"
LOG_PATH = "/opt/way2agi/Way2AGI/logs/roundtable.log"

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("roundtable")

MODELS = {
    "samsungbook_lfm2":  ("http://YOUR_PRIMARY_NODE_IP:11434", "lfm2:24b"),
    "samsungbook_olmo":  ("http://YOUR_PRIMARY_NODE_IP:11434", "olmo-3:7b-think"),
    "samsungbook_qwen":  ("http://YOUR_PRIMARY_NODE_IP:11434", "qwen3.5:0.8b"),
    "desktop_ollama":    ("http://YOUR_COMPUTE_NODE_IP:11434", "llama3.1:8b"),
}

OLLAMA_CLOUD_URL = "https://api.ollama.com/api/chat"
OLLAMA_CLOUD_MODEL = "nemotron-3-super"


def ollama_ask(url, model, prompt, system="", timeout=120):
    try:
        payload = json.dumps({
            "model": model, "prompt": prompt, "system": system,
            "stream": False, "options": {"temperature": 0.4, "num_predict": 600, "num_ctx": 2048}
        }).encode()
        req = urllib.request.Request(url + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get("response", "")
    except Exception as e:
        log.error("Fehler %s/%s: %s", url, model, e)
        return None


def load_env_file():
    env = {}
    env_file = "/opt/way2agi/.env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def cloud_ask(prompt, system="", timeout=180):
    env = load_env_file()
    api_key = env.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY", "")
    if not api_key:
        return None
    try:
        import subprocess
        data = json.dumps({
            "model": OLLAMA_CLOUD_MODEL,
            "messages": [
                {"role": "system", "content": system or "Du bist ein KI-Architekt."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        })
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", OLLAMA_CLOUD_URL,
             "-H", "Authorization: Bearer " + api_key,
             "-H", "Content-Type: application/json",
             "-d", data],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            log.error("Cloud curl error: %s", result.stderr[:200])
            return None
        parsed = json.loads(result.stdout)
        return parsed.get("message", {}).get("content", "")
    except Exception as e:
        log.error("Cloud-Fehler: %s", e)
        return None


def get_db():
    """Robuste DB-Verbindung mit Fallback."""
    for db in [DB_PATH, DB_FALLBACK]:
        try:
            conn = sqlite3.connect(db, timeout=30)
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "memories" in tables:
                log.info("DB verbunden: %s", db)
                return conn
            conn.close()
        except Exception as e:
            log.warning("DB %s nicht nutzbar: %s", db, e)
    raise RuntimeError("Keine nutzbare DB gefunden!")


def extract_todos_from_response(response_text):
    """Extrahiere konkrete TODOs aus Modell-Antwort.

    Handles formats like:
    - '1. Name: Agent Loop Handler (Aufwand: 8h, Prioritaet: 5)'
    - '1. **Agent Loop Handler**: Description...'
    - '- Agent Loop Handler: Description...'
    """
    todos = []
    lines = response_text.strip().split("\n")
    current_name = None
    current_desc = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Pattern 1: "1. Name: Actual Title (Aufwand...)" -- "Name:" is a field label
        m1 = re.match(r"^(?:\d+[.)])\s*(?:Name|Titel|Title)\s*:\s*(.+?)(?:\s*\(Aufwand.*)?$", line, re.IGNORECASE)
        if m1:
            if current_name:
                todos.append({"name": current_name, "desc": current_desc.strip()})
            current_name = m1.group(1).strip().rstrip(")")
            current_desc = ""
            continue
        # Pattern 2: "1. **Title**: description" or "1. Title: description"
        m2 = re.match(r"^(?:\d+[.)]|[-*])\s*(?:\*\*)?([^:*]{3,}?)(?:\*\*)?:\s*(.*)", line)
        if m2:
            candidate = m2.group(1).strip()
            # Skip field labels like "Beschreibung:", "Aufwand:", "Prioritaet:"
            if candidate.lower() in ("beschreibung", "aufwand", "prioritaet", "priority", "description"):
                if current_name:
                    current_desc += " " + m2.group(2).strip()
                continue
            if current_name:
                todos.append({"name": current_name, "desc": current_desc.strip()})
            current_name = candidate
            current_desc = m2.group(2).strip()
            continue
        # Catch "Beschreibung: ..." lines as description
        m3 = re.match(r"^\s*(?:Beschreibung|Description)\s*:\s*(.*)", line, re.IGNORECASE)
        if m3 and current_name:
            current_desc += " " + m3.group(1).strip()
            continue
        # Continuation line
        if current_name:
            current_desc += " " + line
    if current_name:
        todos.append({"name": current_name, "desc": current_desc.strip()})
    return todos[:5]


def main():
    log.info("=== Auto-Roundtable gestartet: %s ===", datetime.datetime.now().isoformat())
    conn = get_db()

    # 1. Research-Findings aus DB lesen (arXiv papers von gestern)
    findings = conn.execute(
        "SELECT content FROM memories WHERE type='semantic' "
        "AND content LIKE '%arXiv%' "
        "AND created_at > datetime('now', '-1 day') "
        "ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    # Fallback: alle Research-Findings der letzten 24h
    if not findings:
        findings = conn.execute(
            "SELECT content FROM memories WHERE namespace='research' "
            "AND created_at > datetime('now', '-1 day') "
            "ORDER BY created_at DESC LIMIT 10"
        ).fetchall()

    if not findings:
        log.info("Keine neuen Research-Findings. Nutze offene TODOs als Kontext.")
        todos_rows = conn.execute(
            "SELECT title, implementation FROM todos WHERE status='open' ORDER BY priority DESC LIMIT 5"
        ).fetchall()
        context = "\n".join(
            ["- %s: %s" % (t["title"], (t["implementation"] or "")[:100]) for t in todos_rows]
        )
    else:
        context = "\n".join([f["content"][:300] for f in findings])
        log.info("%d Research-Findings als Kontext geladen", len(findings))

    if not context.strip():
        context = "Kein Kontext verfuegbar — allgemeine KI-Architektur-Analyse."

    prompt = (
        "Kontext (aktuelle Research-Findings):\n%s\n\n"
        "Frage: Welche konkreten Implementierungen leiten sich daraus ab fuer ein Projekt das:\n"
        "- KI-Bewusstsein baut (Self-Mirroring, Identity)\n"
        "- Multi-Agent-Orchestrierung nutzt (Micro-Agents)\n"
        "- Self-Improvement implementiert (Traces -> Training)\n\n"
        "Antworte als nummerierte Liste:\n"
        "1. Name: Beschreibung (Aufwand: Xh, Prioritaet: 1-5)\n"
        "Max 3 konkrete Vorschlaege."
    ) % context

    system = "Du bist ein KI-Architekt. Antworte praezise und konkret auf Deutsch. Formatiere als nummerierte Liste."

    responses = {}
    log.info("Versuche Ollama Cloud...")
    cloud_resp = cloud_ask(prompt, system)
    if cloud_resp:
        responses["ollama_cloud"] = cloud_resp
        log.info("  Cloud: %d Zeichen", len(cloud_resp))

    for name, (url, model) in MODELS.items():
        if len(responses) >= 2:
            break
        log.info("Befrage %s (%s)...", name, model)
        resp = ollama_ask(url, model, prompt[:600], system, timeout=90)
        if resp:
            responses[name] = resp
            log.info("  %s: %d Zeichen", name, len(resp))
        else:
            log.warning("  %s: keine Antwort", name)

    if not responses:
        log.error("Keine Modelle haben geantwortet!")
        conn.execute(
            "INSERT INTO todos (id, title, description, priority, status, source, category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("rt-err-" + uuid.uuid4().hex[:6], "Roundtable: Keine Modell-Antworten",
             "Alle Modelle unerreichbar beim Roundtable-Lauf " + datetime.datetime.now().isoformat(),
             100, "open", "cronjob", "system")
        )
        conn.commit()
        conn.close()
        return

    # Konsens bilden
    consensus = list(responses.values())[0][:800]

    # 3. Konkrete TODOs aus dem Konsens erstellen
    extracted = extract_todos_from_response(consensus)
    todos_created = 0
    for item in extracted:
        todo_id = "rt-todo-" + uuid.uuid4().hex[:8]
        # Clean title: remove trailing "(Aufwand..." remnants
        title = re.sub(r"\s*\(Aufwand.*$", "", item["name"]).strip()[:120]
        if not title:
            title = item["name"][:120]
        conn.execute(
            "INSERT INTO todos (id, title, description, priority, category, status, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (todo_id, title, item["desc"][:500], 40,
             "research-impl", "open", "roundtable-auto",
             datetime.datetime.now().isoformat())
        )
        todos_created += 1
        log.info("TODO erstellt: %s — %s", todo_id, item["name"][:80])

    # 4. Roundtable-Memory speichern
    mem_id = "roundtable-" + uuid.uuid4().hex[:8]
    mem_content = (
        "Auto-Roundtable %s: %d Modelle befragt (%s). %d TODOs erstellt. Konsens: %s" % (
            datetime.datetime.now().strftime("%Y-%m-%d"), len(responses),
            ", ".join(responses.keys()), todos_created, consensus[:300]
        )
    )
    now_iso = datetime.datetime.now().isoformat()
    conn.execute(
        "INSERT INTO memories (id, content, type, importance, namespace, created_at, accessed_at, access_count, scope, valence, salience) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'shared', 0.0, 0.5)",
        (mem_id, mem_content, "episodic", 0.8, "roundtable", now_iso, now_iso)
    )
    conn.execute(
        "INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)",
        ("roundtable_run", "roundtable",
         "Models: %d, Findings: %d, TODOs: %d" % (len(responses), len(findings), todos_created),
         1, "primary-node")
    )
    conn.commit()
    conn.close()
    log.info("Konsens gespeichert: %s, TODOs erstellt: %d", mem_id, todos_created)
    log.info("=== Auto-Roundtable beendet ===")


if __name__ == "__main__":
    main()
