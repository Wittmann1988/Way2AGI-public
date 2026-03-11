"""
Way2AGI Node Awareness — Shared Module fuer alle Daemons.

Jeder Node (Jetson, Desktop, Zenbook, S24) importiert dieses Modul.
Es gibt ihm:
1. Aufgaben-Bewusstsein — kennt aktuelle TODOs und Prioritaeten
2. Regel-Bewusstsein — prueft GoalGuard bei jeder Aktion
3. Selbstverwaltung — managed eigenen RAM/Speicher

Usage:
    from node_awareness import NodeAwareness
    awareness = NodeAwareness(node_name="desktop")

    # Vor jeder Aktion:
    check = awareness.check_rules("Deploy new model to production")
    if not check["allowed"]:
        print(f"BLOCKED: {check['violations']}")

    # Aufgaben abrufen:
    todos = awareness.get_todos()

    # System aufraumen:
    awareness.cleanup_system()
"""

import json
import logging
import os
import platform
import shutil
import subprocess

log = logging.getLogger("node-awareness")


class NodeAwareness:
    """Gibt jedem Node Bewusstsein ueber Aufgaben, Regeln und Systemstatus."""

    # Alle aktiven Regeln — synchronisiert mit GoalGuard
    RULES = {
        "Z0": {
            "name": "Opus ist der Architekt",
            "check": "Opus orchestriert nur — Ausfuehrung an Nodes delegieren",
            "severity": "warn",
            "keywords": ["opus", "architekt"],
        },
        "Z3": {
            "name": "Alle Modelle einbeziehen",
            "check": "Wurden ALLE verfuegbaren Modelle einbezogen?",
            "severity": "block",
            "keywords": ["design", "konzept", "roundtable", "entscheidung"],
        },
        "Z6": {
            "name": "Pipeline zuerst",
            "check": "Laeuft die Z6 Self-Improving Pipeline?",
            "severity": "block",
            "keywords": ["feature", "neu", "implement", "build"],
        },
        "R1": {
            "name": "Research zuerst",
            "check": "Wurde geprueft ob das schon existiert?",
            "severity": "block",
            "keywords": ["implement", "build", "feature"],
        },
        "S1": {
            "name": "Desktop immer erreichbar",
            "check": "Desktop muss erreichbar sein — Network Agent nutzen",
            "severity": "block",
            "keywords": ["desktop", "offline"],
        },
        "S2": {
            "name": "Ollama /no_think",
            "check": "/no_think im System-Prompt fuer structured output",
            "severity": "warn",
            "keywords": ["qwen3", "thinking", "json"],
        },
        "E011": {
            "name": "Alle Modelle BLOCKER",
            "check": "Groq? Gemini? OpenAI? OpenRouter? Sidekick? Desktop? Jetson?",
            "severity": "block",
            "keywords": ["agent", "dispatch", "roundtable"],
        },
    }

    def __init__(self, node_name: str) -> None:
        self.node_name = node_name
        self.todos: list[dict] = []
        self.completed_todos: list[dict] = []
        self._load_todos()

    def check_rules(self, action: str) -> dict:
        """Prueft eine Aktion gegen alle Regeln. Wie GoalGuard, aber lokal."""
        action_lower = action.lower()
        violations = []

        for rule_id, rule in self.RULES.items():
            triggered = False
            for kw in rule.get("keywords", []):
                if kw.lower() in action_lower:
                    triggered = True
                    break

            if triggered:
                violations.append({
                    "rule_id": rule_id,
                    "name": rule["name"],
                    "check": rule["check"],
                    "severity": rule["severity"],
                })

        has_blocks = any(v["severity"] == "block" for v in violations)
        return {
            "action": action,
            "allowed": not has_blocks,
            "violations": violations,
            "rules_checked": len(self.RULES),
        }

    def get_todos(self) -> list[dict]:
        """Aktuelle TODOs nach Prioritaet sortiert."""
        return sorted(self.todos, key=lambda t: t.get("priority", 99))

    def add_todo(self, title: str, priority: int = 5, source: str = "auto") -> None:
        """Neues TODO hinzufuegen."""
        self.todos.append({
            "title": title,
            "priority": priority,
            "source": source,
            "node": self.node_name,
            "status": "pending",
        })
        self._save_todos()

    def complete_todo(self, title: str) -> None:
        """TODO als erledigt markieren."""
        for todo in self.todos:
            if todo["title"] == title:
                todo["status"] = "completed"
                self.completed_todos.append(todo)
                self.todos.remove(todo)
                self._save_todos()
                return

    def get_system_status(self) -> dict:
        """Systemstatus: RAM, Disk, CPU."""
        status = {
            "node": self.node_name,
            "platform": platform.system(),
            "machine": platform.machine(),
        }

        # RAM
        try:
            import psutil
            mem = psutil.virtual_memory()
            status["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
            status["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
            status["ram_percent"] = mem.percent
            status["ram_available_gb"] = round(mem.available / (1024 ** 3), 1)
        except ImportError:
            # Fallback ohne psutil (z.B. auf Android)
            try:
                with open("/proc/meminfo") as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.startswith("MemTotal:"):
                            status["ram_total_gb"] = round(int(line.split()[1]) / (1024 * 1024), 1)
                        elif line.startswith("MemAvailable:"):
                            status["ram_available_gb"] = round(int(line.split()[1]) / (1024 * 1024), 1)
            except Exception:
                pass

        # Disk
        try:
            disk = shutil.disk_usage("/")
            status["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
            status["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
            status["disk_percent"] = round((disk.used / disk.total) * 100, 1)
        except Exception:
            pass

        return status

    def cleanup_system(self) -> dict:
        """Raeumt das System auf — befreit RAM und Disk."""
        cleaned = {"actions": []}

        # 1. Python Garbage Collection
        import gc
        collected = gc.collect()
        cleaned["actions"].append(f"Python GC: {collected} objects collected")

        # 2. Temp-Dateien aufraumen (plattformabhaengig)
        system = platform.system()
        if system == "Linux":
            tmp_dirs = ["/tmp/way2agi_*", "/tmp/jetson_daemon*"]
            # Auf Android/Termux
            prefix_tmp = os.environ.get("PREFIX", "") + "/tmp"
            if os.path.exists(prefix_tmp):
                tmp_dirs.append(f"{prefix_tmp}/way2agi_*")

            for pattern in tmp_dirs:
                import glob
                old_files = glob.glob(pattern)
                for f in old_files:
                    try:
                        if os.path.isfile(f):
                            age_hours = (os.time() - os.path.getmtime(f)) / 3600
                            if age_hours > 24:
                                os.remove(f)
                                cleaned["actions"].append(f"Removed old temp: {f}")
                    except Exception:
                        pass

        elif system == "Windows":
            # Windows-spezifische Aufraemung
            temp = os.environ.get("TEMP", "")
            if temp:
                cleaned["actions"].append(f"Windows TEMP: {temp} (manual cleanup recommended)")

        # 3. Ollama Cache pruefen (wenn vorhanden)
        ollama_cache = os.path.expanduser("~/.ollama/models/blobs")
        if os.path.exists(ollama_cache):
            try:
                cache_size = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, dn, filenames in os.walk(ollama_cache)
                    for f in filenames
                )
                cleaned["ollama_cache_gb"] = round(cache_size / (1024 ** 3), 1)
            except Exception:
                pass

        log.info("System cleanup: %d actions", len(cleaned["actions"]))
        return cleaned

    def _todo_path(self) -> str:
        """Pfad fuer persistente TODO-Datei."""
        data_dir = os.environ.get(
            "WAY2AGI_DATA",
            os.path.expanduser("~/.way2agi"),
        )
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, f"todos_{self.node_name}.json")

    def _load_todos(self) -> None:
        """Lade TODOs von Disk."""
        path = self._todo_path()
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                    self.todos = data.get("pending", [])
                    self.completed_todos = data.get("completed", [])
            except (json.JSONDecodeError, KeyError):
                self.todos = []
                self.completed_todos = []

    def _save_todos(self) -> None:
        """Speichere TODOs auf Disk."""
        path = self._todo_path()
        with open(path, "w") as f:
            json.dump({
                "pending": self.todos,
                "completed": self.completed_todos[-50:],  # Letzte 50 behalten
            }, f, indent=2, ensure_ascii=False)
