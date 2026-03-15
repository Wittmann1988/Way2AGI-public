#!/usr/bin/env python3
"""Way2AGI Verified Answer Agent — prueft Aussagen auf Wahrheitsgehalt."""
import sqlite3
import json
import time
import subprocess
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from datetime import datetime

DB_PATH = "/opt/way2agi/memory/db/elias_memory.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
PORT = 8180
log = logging.getLogger("verify-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("""CREATE TABLE IF NOT EXISTS verified_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        statement TEXT,
        verified BOOLEAN,
        method TEXT,
        details TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()

def verify_service(service_name):
    try:
        result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() == "active"
    except:
        return None

def verify_url(url):
    try:
        import requests
        r = requests.get(url, timeout=5)
        return r.status_code == 200
    except:
        return False

def verify_with_model(statement):
    try:
        import requests
        payload = {"model": "qwen3.5:0.8b", "prompt": f"Pruefe ob diese Aussage faktisch korrekt ist. Antworte NUR mit true oder false: '{statement}'", "stream": False, "options": {"num_predict": 10, "think": False}}
        r = requests.post(OLLAMA_URL, json=payload, timeout=15)
        result = r.json().get("response", "").strip().lower()
        return "true" in result
    except:
        return None

def process_statement(text):
    text_lower = text.lower()
    if "service" in text_lower and ("laeuft" in text_lower or "aktiv" in text_lower or "running" in text_lower):
        words = text.split()
        for w in words:
            if "way2agi" in w or w.endswith(".service"):
                return verify_service(w), "systemctl"
    if "http" in text_lower:
        import re
        urls = re.findall(r'http[s]?://[^\s]+', text)
        if urls:
            return verify_url(urls[0]), "http-check"
    return verify_with_model(text), "model-check"

def worker():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            cur = conn.execute("SELECT id, statement FROM verified_answers WHERE verified IS NULL LIMIT 1")
            row = cur.fetchone()
            if row:
                stmt_id, statement = row
                result, method = process_statement(statement)
                conn.execute("UPDATE verified_answers SET verified=?, method=?, details=? WHERE id=?",
                    (result, method, f"checked at {datetime.now().isoformat()}", stmt_id))
                conn.commit()
                log.info(f"Verified [{method}]: {statement[:80]} -> {result}")
            conn.close()
        except Exception as e:
            log.error(f"Worker error: {e}")
        time.sleep(3)

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('content-length', 0))
        data = self.rfile.read(length)
        stmt = json.loads(data.decode()).get("statement", "")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("INSERT INTO verified_answers (statement) VALUES (?)", (stmt,))
        conn.commit()
        conn.close()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"status": "queued"}).encode())
    
    def do_GET(self):
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        rows = conn.execute("SELECT id, statement, verified, method, created_at FROM verified_answers ORDER BY id DESC LIMIT 20").fetchall()
        conn.close()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps([{"id":r[0],"statement":r[1],"verified":r[2],"method":r[3],"created_at":r[4]} for r in rows]).encode())
    
    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    init_db()
    Thread(target=worker, daemon=True).start()
    log.info(f"Verified Answer Agent auf Port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
