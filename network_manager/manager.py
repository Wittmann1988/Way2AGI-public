#!/usr/bin/env python3
"""
Way2AGI NetworkManager
======================
Hauptregel (R011): Sorge fuer staendige Verfuegbarkeit ALLER Ressourcen.

Aufgaben:
1. Health-Checks alle 60s auf alle Nodes + Modelle
2. Auto-Recovery bei Ausfall (Restart, Failover)
3. Modell-Registry staendig aktuell halten
4. Orchestrator informieren: Welche Modelle wo verfuegbar
5. Fehler dokumentieren, nie hinnehmen

Laeuft als Daemon auf Jetson (Always-On).
"""

import json
import time
import sqlite3
import urllib.request
import urllib.error
import logging
import os
import sys
import subprocess
from datetime import datetime

DB_PATH = "/data/way2agi/memory/memory.db"
LOG_PATH = "/data/way2agi/memory/logs/network_manager.log"
CHECK_INTERVAL = 60

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("network-mgr")

NODES = {
    "jetson": {
        "ollama_url": "http://localhost:11434",
        "llama_cpp_url": "http://localhost:8080",
        "daemon_url": "http://localhost:8050",
        "ssh": None,
        "role": "controller",
    },
    "desktop": {
        "ollama_url": "http://YOUR_DESKTOP_IP:11434",
        "llama_cpp_url": "http://YOUR_DESKTOP_IP:8080",
        "daemon_url": "http://YOUR_DESKTOP_IP:8100",
        "ssh": "YOUR_SSH_USER@YOUR_DESKTOP_IP",
        "role": "compute",
    },
    "zenbook": {
        "ollama_url": "http://YOUR_LAPTOP_IP:11434",
        "llama_cpp_url": "http://YOUR_LAPTOP_IP:8080",
        "daemon_url": "http://YOUR_LAPTOP_IP:8150",
        "ssh": "YOUR_SSH_USER@YOUR_LAPTOP_IP",
        "role": "orchestrator",
    },
    "s24": {
        "ollama_url": "http://YOUR_MOBILE_IP:11434",
        "llama_cpp_url": None,
        "daemon_url": "http://YOUR_MOBILE_IP:8200",
        "ssh": None,
        "role": "lite",
    },
}


class NetworkManager:
    def __init__(self):
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self.node_status = {}
        self.consecutive_failures = {}

    def check_ollama(self, name, url, timeout=5):
        start = time.time()
        try:
            req = urllib.request.Request(url + "/api/tags", method="GET")
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read())
            latency = (time.time() - start) * 1000
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m["name"],
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "device": name,
                })
            return True, models, latency
        except Exception:
            return False, [], 0

    def check_llama_cpp(self, name, url, timeout=5):
        """Prueft ob llama-server (llama.cpp) erreichbar ist."""
        if not url:
            return False, None, 0
        start = time.time()
        try:
            req = urllib.request.Request(url + "/health", method="GET")
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read())
            latency = (time.time() - start) * 1000
            status = data.get("status", "unknown")
            slots = data.get("slots_idle", 0)
            return status == "ok", {"slots_idle": slots, "status": status}, latency
        except Exception:
            return False, None, 0

    def check_all_nodes(self):
        results = {}
        for name, config in NODES.items():
            online, models, latency = self.check_ollama(name, config["ollama_url"])

            # llama.cpp Server pruefen
            llama_online, llama_info, llama_latency = self.check_llama_cpp(
                name, config.get("llama_cpp_url"))

            results[name] = {
                "online": online or llama_online,
                "models": models,
                "model_count": len(models),
                "latency_ms": round(latency, 1),
                "role": config["role"],
                "last_check": datetime.now().isoformat(),
                "llama_cpp": {
                    "online": llama_online,
                    "url": config.get("llama_cpp_url"),
                    "latency_ms": round(llama_latency, 1),
                    "info": llama_info,
                } if config.get("llama_cpp_url") else None,
            }

            if online:
                self.consecutive_failures[name] = 0
                if not self.node_status.get(name, {}).get("online"):
                    log.info("NODE ONLINE: %s (%d Modelle, %.0fms)", name, len(models), latency)
            else:
                self.consecutive_failures[name] = self.consecutive_failures.get(name, 0) + 1
                failures = self.consecutive_failures[name]
                log.warning("NODE OFFLINE: %s (Versuch %d)", name, failures)

                if failures >= 3 and config.get("ssh"):
                    self.attempt_recovery(name, config)

        self.node_status = results
        return results

    def attempt_recovery(self, name, config):
        log.info("AUTO-RECOVERY: Versuche %s wiederherzustellen...", name)
        ssh_target = config["ssh"]
        try:
            ip = config["ollama_url"].split("//")[1].split(":")[0]
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", ip],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                log.error("  %s: Nicht pingbar. Hardware-Problem?", name)
                self._log_error(name, "%s nicht pingbar — moeglicherweise ausgeschaltet" % name)
                return

            ssh_cmd = ["ssh", "-o", "ConnectTimeout=5"] + ssh_target.split() + ["ollama", "serve"]
            subprocess.Popen(ssh_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("  %s: Ollama restart versucht via SSH", name)
        except Exception as e:
            log.error("  %s: Recovery fehlgeschlagen: %s", name, e)

    def get_all_available_models(self):
        all_models = []
        for name, status in self.node_status.items():
            if status["online"]:
                for model in status["models"]:
                    # Bestimme besten Endpoint: llama.cpp bevorzugt (parallel), Ollama als Fallback
                    llama_info = status.get("llama_cpp")
                    if llama_info and llama_info.get("online"):
                        best_url = NODES[name].get("llama_cpp_url")
                        backend = "llama.cpp"
                    else:
                        best_url = NODES[name]["ollama_url"]
                        backend = "ollama"

                    all_models.append({
                        "model": model["name"],
                        "device": name,
                        "url": best_url,
                        "ollama_url": NODES[name]["ollama_url"],
                        "llama_cpp_url": NODES[name].get("llama_cpp_url"),
                        "backend": backend,
                        "latency_ms": status["latency_ms"],
                        "size_gb": model["size_gb"],
                    })
        return all_models

    def update_db(self):
        c = self.db.cursor()
        online_count = sum(1 for s in self.node_status.values() if s["online"])
        total_models = sum(s["model_count"] for s in self.node_status.values() if s["online"])
        c.execute(
            "INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)",
            ("health_check", "network_manager",
             "Nodes: %d/%d online, Models: %d" % (online_count, len(NODES), total_models),
             1, "jetson")
        )

        for name, status in self.node_status.items():
            if not status["online"] and self.consecutive_failures.get(name, 0) >= 3:
                self._log_error(name, "%s nicht erreichbar seit %d Checks" % (name, self.consecutive_failures[name]))

        self.db.commit()

    def _log_error(self, node, description):
        c = self.db.cursor()
        error_code = "ENET_%s" % node.upper()
        c.execute(
            "INSERT OR REPLACE INTO errors (id, error_code, description, category, rule_violated, severity, last_seen, status) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            (error_code, error_code, description, "network", "R011", "high", "open")
        )
        self.db.commit()

    def report(self):
        lines = ["=== NetworkManager Report %s ===" % datetime.now().strftime("%H:%M:%S")]
        for name, status in self.node_status.items():
            icon = "ON" if status["online"] else "OFF"
            llama = status.get("llama_cpp")
            llama_str = ""
            if llama and llama.get("online"):
                llama_str = " | llama.cpp: ON (%.0fms)" % llama["latency_ms"]
            elif llama:
                llama_str = " | llama.cpp: OFF"
            lines.append("  [%s] %s: %d Modelle, %.0fms%s" % (icon, name, status["model_count"], status["latency_ms"], llama_str))

        models = self.get_all_available_models()
        lines.append("  Gesamt: %d Modelle auf %d Nodes" % (
            len(models), sum(1 for s in self.node_status.values() if s["online"])
        ))
        return "\n".join(lines)

    def run_forever(self):
        log.info("NetworkManager gestartet (Check alle %ds)", CHECK_INTERVAL)
        while True:
            try:
                self.check_all_nodes()
                self.update_db()
                log.info(self.report())
            except Exception as e:
                log.error("NetworkManager Fehler: %s", e)
            time.sleep(CHECK_INTERVAL)


def main():
    mgr = NetworkManager()

    if "--daemon" in sys.argv:
        mgr.run_forever()
    else:
        mgr.check_all_nodes()
        mgr.update_db()
        print(mgr.report())
        print("\nAlle Modelle fuer Orchestrator:")
        for m in mgr.get_all_available_models():
            print("  %s @ %s (%.0fms, %.1fGB)" % (m["model"], m["device"], m["latency_ms"], m["size_gb"]))


if __name__ == "__main__":
    main()
