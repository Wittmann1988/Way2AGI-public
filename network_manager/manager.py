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

Laeuft als Daemon auf Inference Node (Always-On).
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

# WAL (Way2AGI Agent Language) Integration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.agent_language import nm_report_node, encode, log_message, decode, shortcut_node_status, shortcut_task, SHORTCUTS
    WAL_ENABLED = True
except ImportError:
    WAL_ENABLED = False

DB_PATH = "/opt/way2agi/memory/memory.db"
LOG_PATH = "/opt/way2agi/memory/logs/network_manager.log"
CHECK_INTERVAL = 60

# Wake-on-LAN fuer Desktop
DESKTOP_MAC = "34:5a:60:56:1f:bd"
WOL_COOLDOWN = 600  # Maximal 1x pro 10 Minuten
WOL_WAIT_AFTER = 60  # Nach WoL 60s warten bevor erneut geprueft wird

# SSD Backup Monitoring
SSD_CHECK_INTERVAL = 1800  # 30 Minuten
BACKUP_MAX_AGE_HOURS = 7
TABLET_SSH = "YOUR_MOBILE_NODE_IP"
TABLET_SSH_PORT = 8022
TABLET_USER = "root"
SSD_MOUNT_PATH = "/storage/2872-6065"
BACKUP_SCRIPT_PATH = "/data/data/com.termux/files/home/scripts/backup_to_ssd.sh"

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("network-mgr")

NODES = {
    "inference-node": {
        "ollama_url": "http://localhost:11434",
        "llama_cpp_url": "http://localhost:8080",
        "daemon_url": "http://localhost:8050",
        "ssh": None,
        "role": "controller",
    },
    "desktop": {
        "ollama_url": "http://YOUR_COMPUTE_NODE_IP:11434",
        "llama_cpp_url": "http://YOUR_COMPUTE_NODE_IP:8080",
        "daemon_url": "http://YOUR_COMPUTE_NODE_IP:8100",
        "ssh": "YOUR_USER@YOUR_COMPUTE_NODE_IP",
        "role": "compute",
    },
    "npu-node": {
        "ollama_url": "http://YOUR_NPU_NODE_IP:11434",
        "llama_cpp_url": "http://YOUR_NPU_NODE_IP:8080",
        "daemon_url": "http://YOUR_NPU_NODE_IP:8150",
        "ssh": "YOUR_USER@YOUR_NPU_NODE_IP",
        "role": "orchestrator",
    },
    "s24": {
        "ollama_url": "http://YOUR_MOBILE_NODE_IP:11434",
        "llama_cpp_url": None,
        "daemon_url": "http://YOUR_MOBILE_NODE_IP:8200",
        "ssh": None,
        "role": "lite",
    },
}


class NetworkManager:
    def __init__(self):
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute("PRAGMA journal_mode=WAL;")
        self.db.execute("PRAGMA busy_timeout = 5000;")
        self.db.row_factory = sqlite3.Row
        self.node_status = {}
        self.consecutive_failures = {}
        self._last_wol_time = 0

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
                    log.info("%s|%dM", shortcut_node_status(name, True, int(latency)) if WAL_ENABLED else "[ON] " + name, len(models))
                # WAL: Status an Orchestrator melden
                if WAL_ENABLED:
                    wal_msg = nm_report_node(name, "up", int(latency))
                    log.debug("WAL: %s", wal_msg)
                    log_message(wal_msg)
            else:
                self.consecutive_failures[name] = self.consecutive_failures.get(name, 0) + 1
                failures = self.consecutive_failures[name]
                log.warning("%s|F%d", shortcut_node_status(name, False) if WAL_ENABLED else "[OFF] " + name, failures)
                # WAL: Offline-Status melden
                if WAL_ENABLED:
                    wal_msg = nm_report_node(name, "down", 0)
                    log.debug("WAL: %s", wal_msg)
                    log_message(wal_msg)

                if failures >= 3 and config.get("ssh"):
                    self.attempt_recovery(name, config)

                # Desktop spezifisch: WoL senden wenn Desktop gebraucht wird
                if name == "desktop" and failures >= 2:
                    if self.desktop_needed():
                        wol_sent = self.wake_desktop()
                        if wol_sent:
                            log.info("Warte %ds nach WoL bevor naechster Check...", WOL_WAIT_AFTER)
                            time.sleep(WOL_WAIT_AFTER)

        self.node_status = results
        return results

    def wake_desktop(self):
        """Sendet Wake-on-LAN an Desktop PC."""
        now = time.time()
        if (now - self._last_wol_time) < WOL_COOLDOWN:
            remaining = int(WOL_COOLDOWN - (now - self._last_wol_time))
            log.info("WoL-Cooldown aktiv, naechster Versuch in %ds", remaining)
            return False
        try:
            result = subprocess.run(
                ["wakeonlan", DESKTOP_MAC],
                capture_output=True, text=True, timeout=10
            )
            self._last_wol_time = time.time()
            if result.returncode == 0:
                log.info("W!:D")
                if WAL_ENABLED:
                    wal_msg = encode("NM", "OR", "WOL", {"node": "desktop", "mac": DESKTOP_MAC})
                    log_message(wal_msg)
                return True
            else:
                log.error("WoL fehlgeschlagen: %s", result.stderr)
                return False
        except Exception as e:
            log.error("WoL Exception: %s", e)
            return False

    def desktop_needed(self):
        """Prueft ob offene Tasks existieren die Desktop-GPU brauchen."""
        try:
            c = self.db.cursor()
            c.execute(
                "SELECT COUNT(*) FROM action_log "
                "WHERE success = 0 "
                "AND (input_summary LIKE '%desktop%' "
                "     OR input_summary LIKE '%training%' "
                "     OR input_summary LIKE '%gpu%' "
                "     OR input_summary LIKE '%RTX%' "
                "     OR module IN ('training', 'abliteration', 'merge', 'gguf')) "
                "AND created_at > datetime('now', '-1 hour')"
            )
            count = c.fetchone()[0]
            if count > 0:
                log.info("Desktop benoetigt: %d offene Tasks gefunden", count)
                return True
        except Exception as e:
            log.debug("Desktop-needed check failed: %s", e)

        # Pruefe auch ob Training-Pipeline laeuft (Datei-basiert)
        training_markers = [
            "/opt/way2agi/Way2AGI/training/.pipeline_active",
            "/tmp/training_needs_desktop",
        ]
        for marker in training_markers:
            if os.path.exists(marker):
                log.info("Desktop benoetigt: Marker %s gefunden", marker)
                return True

        return False

    def attempt_recovery(self, name, config):
        log.info("R!:%s", name)
        if WAL_ENABLED:
            wal_msg = encode("NM", "OR", "RST", {"node": name, "reason": "auto_recovery"})
            log_message(wal_msg)
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
             1, "inference-node")
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
        lines = ["NM@%s" % datetime.now().strftime("%H:%M:%S")]
        for name, status in self.node_status.items():
            icon = "ON" if status["online"] else "OFF"
            llama = status.get("llama_cpp")
            llama_str = ""
            if llama and llama.get("online"):
                llama_str = " | llama.cpp: ON (%.0fms)" % llama["latency_ms"]
            elif llama:
                llama_str = " | llama.cpp: OFF"
            sc = shortcut_node_status(name, status["online"], int(status["latency_ms"])) if WAL_ENABLED else "[%s]%s" % (icon, name)
            lines.append("  %s|%dM%s" % (sc, status["model_count"], llama_str))

        models = self.get_all_available_models()
        lines.append("  T:%dM/%dN" % (
            len(models), sum(1 for s in self.node_status.values() if s["online"])
        ))
        # WAL: Report-Zusammenfassung loggen
        if WAL_ENABLED:
            online_nodes = sum(1 for s in self.node_status.values() if s["online"])
            wal_msg = encode("NM", "OR", "RPT", {
                "nodes": str(online_nodes),
                "models": str(len(models)),
                "ts": datetime.now().strftime("%H:%M:%S"),
            })
            log.debug("WAL: %s", wal_msg)
            log_message(wal_msg)
        return "\n".join(lines)


    def check_ssd_backup(self):
        """Prueft ob SSD-Backup auf dem Tablet aktuell ist (alle 30 Min)."""
        now = time.time()
        if not hasattr(self, '_last_ssd_check'):
            self._last_ssd_check = 0

        if (now - self._last_ssd_check) < SSD_CHECK_INTERVAL:
            return  # Noch nicht faellig

        self._last_ssd_check = now
        log.info("0")

        # 1. Tablet erreichbar?
        tablet_reachable = self._check_tablet_reachable()
        if not tablet_reachable:
            self._log_ssd_error("ESSD_TABLET_OFFLINE",
                "Tablet (S24) nicht erreichbar — SSD-Backup kann nicht geprueft werden")
            return

        # 2. SSD gemountet?
        ssd_mounted = self._check_ssd_mounted()
        if not ssd_mounted:
            self._log_ssd_error("ESSD_NOT_MOUNTED",
                "SSD nicht gemountet unter %s auf Tablet" % SSD_MOUNT_PATH)
            return

        # 3. Letztes Backup pruefen
        backup_age = self._get_backup_age()
        if backup_age is None:
            self._log_ssd_error("ESSD_NO_BACKUP",
                "Kein Backup gefunden auf SSD — backup_to_ssd.sh hat nie gelaufen?")
            return

        if backup_age > BACKUP_MAX_AGE_HOURS * 3600:
            hours = backup_age / 3600
            self._log_ssd_error("ESSD_BACKUP_OLD",
                "Letztes SSD-Backup ist %.1f Stunden alt (Max: %d). Cronjob pruefen!" % (hours, BACKUP_MAX_AGE_HOURS))
            log.warning("SSD-Backup VERALTET: %.1fh (Max %dh)", hours, BACKUP_MAX_AGE_HOURS)
        else:
            hours = backup_age / 3600
            log.info(":%.1fh", hours)
            # Alten Fehler schliessen falls vorhanden
            self._close_ssd_errors()

    def _check_tablet_reachable(self):
        """Prueft ob Tablet via SSH erreichbar ist."""
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                 "-p", str(TABLET_SSH_PORT), "%s@%s" % (TABLET_USER, TABLET_SSH), "echo OK"],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0 and "OK" in result.stdout
        except Exception as e:
            log.debug("Tablet SSH check failed: %s", e)
            # Fallback: Ping
            try:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", TABLET_SSH],
                    capture_output=True, timeout=5
                )
                return result.returncode == 0
            except Exception:
                return False

    def _check_ssd_mounted(self):
        """Prueft ob SSD auf dem Tablet gemountet ist."""
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                 "-p", str(TABLET_SSH_PORT), "%s@%s" % (TABLET_USER, TABLET_SSH),
                 "test -d %s && echo MOUNTED" % SSD_MOUNT_PATH],
                capture_output=True, text=True, timeout=10
            )
            return "MOUNTED" in result.stdout
        except Exception:
            return False

    def _get_backup_age(self):
        """Gibt das Alter des letzten Backups in Sekunden zurueck, oder None."""
        try:
            # Pruefe neueste Datei im SSD-Backup-Verzeichnis
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                 "-p", str(TABLET_SSH_PORT), "%s@%s" % (TABLET_USER, TABLET_SSH),
                 "stat -c '%%Y' $(find %s -maxdepth 2 -type f -newer %s/.backup_timestamp -o -name '.backup_timestamp' 2>/dev/null | head -1) 2>/dev/null || stat -c '%%Y' $(ls -t %s/ 2>/dev/null | head -1) 2>/dev/null || echo NONE" % (SSD_MOUNT_PATH, SSD_MOUNT_PATH, SSD_MOUNT_PATH)],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout.strip()
            if output == "NONE" or not output:
                return None
            last_modified = int(output)
            return time.time() - last_modified
        except Exception as e:
            log.debug("Backup age check failed: %s", e)
            return None

    def _log_ssd_error(self, error_code, description):
        """Schreibt SSD-Fehler in die errors Tabelle."""
        c = self.db.cursor()
        c.execute(
            "INSERT OR REPLACE INTO errors (id, error_code, description, category, rule_violated, severity, last_seen, status) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            (error_code, error_code, description, "backup", "R011", "high", "open")
        )
        self.db.commit()
        log.warning("SSD-Error: [%s] %s", error_code, description)

    def _close_ssd_errors(self):
        """Schliesst alte SSD-Fehler wenn Backup wieder aktuell."""
        c = self.db.cursor()
        c.execute(
            "UPDATE errors SET status='resolved', updated_at=datetime('now') "
            "WHERE category='backup' AND status='open'"
        )
        self.db.commit()

    def run_forever(self):
        log.info("NetworkManager gestartet (Check alle %ds)", CHECK_INTERVAL)
        while True:
            try:
                self.check_all_nodes()
                self.update_db()
                self.check_ssd_backup()
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
