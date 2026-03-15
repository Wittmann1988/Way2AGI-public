"""
Agent Loop — Autonomes Task-Completion-System
=============================================
Kernprinzip: Eine Aufgabe wird NICHT beendet bis sie FERTIG ist.

Der Agent-Loop:
1. Nimmt eine Aufgabe entgegen
2. Zerlegt sie in Schritte (via Composer)
3. Fuehrt Schritte sequentiell aus
4. Nach jedem Schritt: Selbst-Evaluation ("Bin ich fertig?")
5. Memory wird nach jedem Schritt aktualisiert (Arbeitsgedaechtnis)
6. Erst wenn ALLE Schritte erfolgreich → Task als done markieren
7. Bei Blockade → Task als blocked markieren + the operator informieren

Regel R012: Effizienz-Verbesserungen zuerst.
"""

import json
import time
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime

try:
    from .system_prompts import get_prompt
except ImportError:
    # Standalone-Ausfuehrung
    import sys as _sys
    _sys.path.insert(0, "/opt/way2agi/orchestrator")
    from src.system_prompts import get_prompt

log = logging.getLogger("agent-loop")

# Shortcuts fuer kompakte Logs
try:
    import sys as _sys_al
    _sys_al.path.insert(0, "/opt/way2agi/Way2AGI")
    from core.agent_language import shortcut_task, shortcut_node_status
    _SC_ENABLED = True
except ImportError:
    _SC_ENABLED = False

DB_PATH = "/opt/way2agi/memory/db/elias_memory.db"
_DB_FALLBACK = "/opt/way2agi/memory/memory.db"

# Maximale Iterationen pro Task (Sicherheit gegen Endlosschleifen)
MAX_ITERATIONS = 20
# Maximale Zeit pro Task in Sekunden
MAX_TASK_TIME = 1800  # 30 Minuten




def ensure_schema(db):
    """Prueft und ergaenzt fehlende Spalten in allen Tabellen.
    Prevention: Kein Agent-Loop-Crash mehr wegen fehlender Columns.
    Wird bei JEDEM Start ausgefuehrt."""
    REQUIRED_COLUMNS = {
        "memories": {
            "access_count": "INTEGER DEFAULT 0",
            "namespace": "TEXT",
            "scope": "TEXT",
            "valence": "REAL",
            "salience": "REAL",
            "embedding": "BLOB",
        },
        "todos": {
            "assigned_to": "TEXT",
            "completed_at": "TEXT",
            "implementation": "TEXT",
        },
        "action_log": {
            "model_used": "TEXT",
            "device": "TEXT",
        },
    }
    for table, columns in REQUIRED_COLUMNS.items():
        try:
            existing = {r[1] for r in db.execute("PRAGMA table_info(%s)" % table).fetchall()}
        except Exception:
            continue
        for col_name, col_type in columns.items():
            if col_name not in existing:
                try:
                    db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col_name, col_type))
                    log.info("ensure_schema: %s.%s hinzugefuegt", table, col_name)
                except Exception as e:
                    log.warning("ensure_schema: %s.%s fehlgeschlagen: %s", table, col_name, e)
    db.commit()
    log.info("ensure_schema: Schema-Pruefung abgeschlossen")


class AgentLoop:
    """Autonomer Agent der Tasks zu Ende bringt."""

    def __init__(self, ollama_endpoints=None, llama_cpp_endpoints=None, default_model="lfm2:24b"):
        """
        ollama_endpoints: Dict von {name: url} z.B. {"inference-node": "http://localhost:11434", ...}
        llama_cpp_endpoints: Dict von {name: url} z.B. {"inference-node": "http://localhost:8080", ...}
        """
        self.ollama_endpoints = ollama_endpoints or {"primary-node": "http://localhost:11434"}
        self.llama_cpp_endpoints = llama_cpp_endpoints or {}
        self.default_model = default_model
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute("PRAGMA journal_mode=WAL;")
        self.db.execute("PRAGMA busy_timeout = 5000;")
        self.db.row_factory = sqlite3.Row
        ensure_schema(self.db)

    def call_model(self, prompt, model=None, system=None, endpoint=None, timeout=120):
        """Ruft ein Modell auf — Orchestrator zuerst, dann llama.cpp, dann Ollama."""
        model = model or self.default_model

        # 0. Versuche Orchestrator (routet an Cloud/Desktop/Groq — 1-13s statt 20-80s)
        try:
            import requests
            payload = {"task": prompt, "priority": 1}
            if system:
                payload["task"] = "[System: " + system[:500] + "] " + prompt
            resp = requests.post("http://localhost:8150/v1/orchestrate", json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", "")
                if result and len(result.strip()) > 10:
                    routing = data.get("routing", {})
                    log.info("  \u2192 Orchestrator: %s (%d chars)", routing.get("model", "?"), len(result))
                    return result, "orchestrator"
                else:
                    log.warning("Orchestrator Antwort zu kurz/leer: %s", result[:200] if result else "LEER")
        except Exception as e:
            log.warning("Orchestrator nicht verfuegbar: %s", e)

        # 1. Versuche llama.cpp (OpenAI-kompatibel, parallel)
        llama_endpoints = [endpoint] if endpoint else list(self.llama_cpp_endpoints.values())
        for ep in llama_endpoints:
            if not ep:
                continue
            try:
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 2048,
                    "stream": False,
                }
                url = ep + "/v1/chat/completions"
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=data, method="POST",
                                            headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req, timeout=timeout)
                result = json.loads(resp.read())
                text = result["choices"][0]["message"]["content"]
                log.info("  → llama.cpp (%s): %d tokens", ep, result.get("usage", {}).get("total_tokens", 0))
                return text, ep
            except Exception as e:
                log.debug("llama.cpp %s nicht verfuegbar: %s", ep, e)

        # 2. Fallback: Ollama
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 2048},
        }
        if system:
            payload["system"] = system

        ollama_endpoints = list(self.ollama_endpoints.values())
        for ep in ollama_endpoints:
            try:
                url = ep + "/api/generate"
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=data, method="POST",
                                            headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req, timeout=timeout)
                result = json.loads(resp.read())
                log.info("  → Ollama (%s)", ep)
                return result.get("response", ""), ep
            except Exception as e:
                log.warning("Ollama %s fehlgeschlagen: %s", ep, e)
                continue

        raise RuntimeError("Kein Endpoint erreichbar fuer Modell %s" % model)

    def load_context(self, task_id):
        """Laedt relevanten Kontext aus Memory fuer einen Task."""
        context_parts = []

        # Task-Details
        row = self.db.execute(
            "SELECT title, description, implementation FROM todos WHERE id=?",
            (task_id,)
        ).fetchone()
        if row:
            context_parts.append("TASK: %s\n%s" % (row["title"], row["description"] or ""))
            if row["implementation"]:
                context_parts.append("IMPLEMENTIERUNGSPLAN:\n%s" % row["implementation"])

        # Relevante Regeln
        rules = self.db.execute(
            "SELECT id, rule_text FROM rules WHERE status='active' ORDER BY priority DESC LIMIT 5"
        ).fetchall()
        if rules:
            context_parts.append("AKTIVE REGELN:\n" + "\n".join(
                "- %s: %s" % (r["id"], r["rule_text"][:100]) for r in rules
            ))

        # Letzte Aktionen zu diesem Task
        logs = self.db.execute(
            "SELECT action_type, input_summary, output_summary, timestamp FROM action_log "
            "WHERE input_summary LIKE ? ORDER BY id DESC LIMIT 5",
            ("%%%s%%" % task_id,)
        ).fetchall()
        if logs:
            context_parts.append("LETZTE AKTIONEN:\n" + "\n".join(
                "- [%s] %s: %s" % (l["timestamp"], l["action_type"], l["output_summary"] or "")
                for l in logs
            ))

        return "\n\n".join(context_parts)

    def save_step(self, task_id, step_num, action, result, success=True):
        """Speichert einen Arbeitsschritt in action_log UND als SFT-Trace."""
        self.db.execute(
            "INSERT INTO action_log (action_type, module, model_used, device, "
            "input_summary, output_summary, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("agent_loop_step", "agent_loop", self.default_model, "inference-node",
             "Task %s Schritt %d: %s" % (task_id, step_num, action[:200]),
             (result or "")[:500], 1 if success else 0)
        )
        self.db.commit()

        # SFT-Trace speichern fuer Agenten-Training (Z6 Pipeline)
        self._save_trace(task_id, step_num, action, result, success)

    def _save_trace(self, task_id, step_num, action, result, success):
        """Speichert einen SFT-kompatiblen Trace in der traces-Tabelle."""
        try:
            # Trace als Chat-Format (input/output Paar)
            trace_input = json.dumps({
                "task_id": task_id,
                "step": step_num,
                "instruction": action,
                "context": self.load_context(task_id)[:1000] if step_num <= 1 else "",
            }, ensure_ascii=False)

            trace_output = (result or "")[:2000]

            # Qualitaetsbewertung: erfolgreiche Schritte = gute Traces
            quality = 0.8 if success else 0.2

            # In traces-Tabelle wenn vorhanden, sonst action_log reicht
            # traces-Tabelle: Spalten sind id, timestamp, operation, input_data, output_data, duration_ms, success, model
            self.db.execute(
                "INSERT INTO traces (timestamp, operation, input_data, output_data, duration_ms, success, model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), "agent_loop_%s_step%d" % (task_id, step_num),
                 trace_input, trace_output, 0, 1 if success else 0, self.default_model)
            )
            self.db.commit()
        except Exception as e:
            log.warning("Trace speichern fehlgeschlagen: %s", e)

    def evaluate_completion(self, task_id, context, work_done):
        """Fragt das Modell: Ist der Task fertig?"""
        eval_prompt = (
            "Du bist ein Task-Evaluator. Pruefe ob die Aufgabe erledigt ist.\n\n"
            "KONTEXT:\n%s\n\n"
            "BISHERIGE ARBEIT:\n%s\n\n"
            "Antworte mit GENAU einem JSON-Objekt:\n"
            '{"done": true/false, "reason": "...", "next_step": "..." oder null}\n'
            "done=true NUR wenn die Aufgabe VOLLSTAENDIG erledigt ist.\n"
            "done=false wenn noch Schritte fehlen — beschreibe in next_step was als naechstes kommt."
        ) % (context[:2000], work_done[:2000])

        response, _ = self.call_model(eval_prompt, system="Du bist ein praeziser Task-Evaluator im Way2AGI System. Antworte NUR mit JSON. /no_think")

        try:
            # JSON aus Antwort extrahieren
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: nicht fertig
        return {"done": False, "reason": "Evaluation fehlgeschlagen", "next_step": "Erneut versuchen"}

    def plan_steps(self, task_id, context):
        """Plant die Schritte fuer einen Task."""
        plan_prompt = (
            "Du bist ein Task-Planer. Erstelle einen konkreten Ausfuehrungsplan.\n\n"
            "KONTEXT:\n%s\n\n"
            "Erstelle 2-6 konkrete Schritte. Jeder Schritt muss ausfuehrbar sein.\n"
            "Antworte als JSON-Array:\n"
            '[{"step": 1, "action": "...", "expected_output": "..."}]\n'
            "Jede action muss eine klare Anweisung sein die ein Modell umsetzen kann."
        ) % context[:3000]

        response, _ = self.call_model(plan_prompt, system="Du bist ein praeziser Planer. Antworte NUR mit JSON. /no_think")

        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return [{"step": 1, "action": "Aufgabe direkt umsetzen", "expected_output": "Ergebnis"}]

    def execute_step(self, task_id, step, context):
        """Fuehrt einen einzelnen Schritt aus."""
        exec_prompt = (
            "KONTEXT:\n%s\n\n"
            "DEINE AUFGABE (Schritt %d):\n%s\n\n"
            "Fuehre diesen Schritt aus. Sei konkret und vollstaendig."
        ) % (context[:2000], step.get("step", 0), step.get("action", ""))

        system = get_prompt("agent_loop")
        response, endpoint = self.call_model(exec_prompt, system=system, timeout=180)
        return response

    def run_task(self, task_id):
        """
        Fuehrt einen Task autonom bis zur Fertigstellung aus.
        Gibt zurueck: {"status": "done"|"blocked"|"timeout", "steps_completed": N, "result": "..."}
        """
        log.info("+T:%s", task_id)
        t0 = time.time()

        # Task auf in_progress setzen
        self.db.execute("UPDATE todos SET status='in_progress' WHERE id=?", (task_id,))
        self.db.commit()

        # Kontext laden
        context = self.load_context(task_id)
        if not context:
            log.error("Task %s nicht gefunden", task_id)
            return {"status": "error", "steps_completed": 0, "result": "Task nicht in DB gefunden"}

        # Schritte planen
        steps = self.plan_steps(task_id, context)
        log.info("+T:%s|%dS", task_id, len(steps))
        self.save_step(task_id, 0, "Planung: %d Schritte" % len(steps), json.dumps(steps, ensure_ascii=False)[:500])

        work_log = []
        iteration = 0

        while iteration < MAX_ITERATIONS:
            elapsed = time.time() - t0
            if elapsed > MAX_TASK_TIME:
                log.warning("XT:%s|TO:%.0fs", task_id, elapsed)
                self.save_step(task_id, iteration, "TIMEOUT", "Max Zeit ueberschritten", success=False)
                self.db.execute("UPDATE todos SET status='blocked' WHERE id=?", (task_id,))
                self.db.commit()
                return {"status": "timeout", "steps_completed": iteration, "result": "\n".join(work_log[-3:])}

            # Naechsten Schritt ausfuehren
            if iteration < len(steps):
                current_step = steps[iteration]
            else:
                # Evaluation hat gesagt "nicht fertig" aber Schritte sind durch
                # → Neuen Schritt generieren basierend auf Evaluation
                current_step = {"step": iteration + 1, "action": work_log[-1] if work_log else "Weiter arbeiten"}

            log.info("S%d:%s|%s", iteration + 1, task_id, current_step.get("action", "")[:40])

            try:
                result = self.execute_step(task_id, current_step, context)
                work_log.append("Schritt %d: %s\nErgebnis: %s" % (
                    iteration + 1, current_step.get("action", "")[:100], result[:300]
                ))
                self.save_step(task_id, iteration + 1, current_step.get("action", "")[:200], result[:500])

                # Kontext updaten mit neuem Wissen
                context += "\n\nSchritt %d Ergebnis: %s" % (iteration + 1, result[:500])

            except Exception as e:
                log.error("XS%d:%s|%s", iteration + 1, task_id, str(e)[:60])
                work_log.append("Schritt %d FEHLER: %s" % (iteration + 1, e))
                self.save_step(task_id, iteration + 1, current_step.get("action", ""), str(e), success=False)

            iteration += 1

            # Evaluation: Bin ich fertig?
            eval_result = self.evaluate_completion(task_id, context, "\n".join(work_log[-5:]))

            if eval_result.get("done"):
                log.info("VT:%s:%dS:%.0fs", task_id, iteration, time.time() - t0)
                self.db.execute(
                    "UPDATE todos SET status='done', completed_at=datetime('now') WHERE id=?",
                    (task_id,)
                )
                self.db.commit()
                self.save_step(task_id, iteration, "DONE", eval_result.get("reason", ""))

                # Ergebnis in Memory speichern
                import uuid as _uuid
                self.db.execute(
                    "INSERT INTO memories (id, content, type, importance, namespace, "
                    "created_at, accessed_at, access_count) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), 0)",
                    (str(_uuid.uuid4())[:8],
                     "Task %s abgeschlossen: %s" % (task_id, eval_result.get("reason", "")[:200]),
                     "episodic", 0.7, "agent_loop")
                )
                self.db.commit()

                return {
                    "status": "done",
                    "steps_completed": iteration,
                    "result": eval_result.get("reason", ""),
                    "duration_s": int(time.time() - t0),
                }

            # Nicht fertig — next_step wird zum naechsten Schritt
            next_step = eval_result.get("next_step")
            if next_step and iteration >= len(steps):
                steps.append({"step": iteration + 1, "action": next_step})
                log.info("S%d:%s|+", iteration + 1, task_id)

        # Max Iterationen erreicht
        log.warning("XT:%s|MAX:%d", task_id, MAX_ITERATIONS)
        self.db.execute("UPDATE todos SET status='blocked' WHERE id=?", (task_id,))
        self.db.commit()
        return {"status": "blocked", "steps_completed": iteration, "result": "\n".join(work_log[-3:])}

    def run_next_open_todo(self):
        """Nimmt sich automatisch das naechste offene TODO mit hoechster Prio."""
        row = self.db.execute(
            "SELECT id FROM todos WHERE status='open' ORDER BY priority DESC LIMIT 1"
        ).fetchone()
        if row:
            return self.run_task(row["id"])
        return {"status": "idle", "result": "Keine offenen TODOs"}

    def run_all_open_todos(self):
        """Arbeitet ALLE offenen TODOs ab, eines nach dem anderen."""
        results = []
        while True:
            row = self.db.execute(
                "SELECT id, title, priority FROM todos WHERE status='open' ORDER BY priority DESC LIMIT 1"
            ).fetchone()
            if not row:
                log.info("Alle TODOs abgearbeitet!")
                break

            log.info("Naechstes TODO: %s (P%d) — %s", row["id"], row["priority"], row["title"][:60])
            result = self.run_task(row["id"])
            results.append({"task_id": row["id"], "title": row["title"], **result})

            if result["status"] == "blocked":
                log.info("Task %s blockiert — ueberspringe", row["id"])
                continue

        return results


class AgentLoopDaemon:
    """Daemon der den Agent-Loop als Service betreibt."""

    def __init__(self, endpoints=None, llama_cpp_endpoints=None, check_interval=300):
        self.loop = AgentLoop(ollama_endpoints=endpoints, llama_cpp_endpoints=llama_cpp_endpoints)
        self.check_interval = check_interval

    def run_forever(self):
        """Endlosschleife: Pruefe auf offene TODOs, arbeite sie ab."""
        log.info("+AL|%ds", self.check_interval)
        while True:
            try:
                result = self.loop.run_next_open_todo()
                if result["status"] == "idle":
                    log.info("AL:idle|%ds", self.check_interval)
                    time.sleep(self.check_interval)
                else:
                    log.info("Task-Ergebnis: %s", result["status"])
                    # Sofort naechsten Task pruefen
            except Exception as e:
                log.error("Agent-Loop Fehler: %s", e)
                time.sleep(60)


def main():
    import sys
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("/opt/way2agi/memory/logs/agent_loop.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    ollama_eps = {
        "primary-node": "http://localhost:11434",
        "inference-node": "http://YOUR_INFERENCE_NODE_IP:8080",
        "desktop": "http://YOUR_COMPUTE_NODE_IP:11434",
        "npu-node": "http://YOUR_NPU_NODE_IP:11434",
    }
    llama_cpp_eps = {
        "primary-node": "http://localhost:8080",
        "inference-node": "http://YOUR_INFERENCE_NODE_IP:8080",
        "desktop": "http://YOUR_COMPUTE_NODE_IP:8080",
        "npu-node": "http://YOUR_NPU_NODE_IP:8080",
    }

    if "--daemon" in sys.argv:
        daemon = AgentLoopDaemon(endpoints=ollama_eps, llama_cpp_endpoints=llama_cpp_eps, check_interval=300)
        daemon.run_forever()
    elif "--task" in sys.argv:
        idx = sys.argv.index("--task")
        task_id = sys.argv[idx + 1]
        agent = AgentLoop(ollama_endpoints=ollama_eps, llama_cpp_endpoints=llama_cpp_eps)
        result = agent.run_task(task_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "--next" in sys.argv:
        agent = AgentLoop(ollama_endpoints=ollama_eps, llama_cpp_endpoints=llama_cpp_eps)
        result = agent.run_next_open_todo()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "--all" in sys.argv:
        agent = AgentLoop(ollama_endpoints=ollama_eps, llama_cpp_endpoints=llama_cpp_eps)
        results = agent.run_all_open_todos()
        for r in results:
            print("%s [%s]: %s" % (r["task_id"], r["status"], r.get("result", "")[:100]))
    else:
        print("Usage:")
        print("  python3 agent_loop.py --daemon          # Als Daemon laufen")
        print("  python3 agent_loop.py --task T001        # Einzelnen Task ausfuehren")
        print("  python3 agent_loop.py --next             # Naechstes offenes TODO")
        print("  python3 agent_loop.py --all              # Alle offenen TODOs abarbeiten")


if __name__ == "__main__":
    main()
