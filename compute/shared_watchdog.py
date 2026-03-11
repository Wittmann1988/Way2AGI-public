"""
Way2AGI Shared Watchdog — Eingebettet in jeden Daemon.

Jeder Node prueft alle 10 Minuten:
1. Ist der Jetson Controller (Port 8050) erreichbar?
2. Laufen die Cronjobs?
3. Falls Controller offline → uebernimmt der naechste Node die Aufgaben.

Redundanz-Kette: Jetson → Desktop → Zenbook → S24
Wenn ein Node merkt dass er der "aelteste" Online-Node ist, wird er zum Acting Controller.

Usage in jedem Daemon:
    from shared_watchdog import Watchdog
    watchdog = Watchdog(my_node_name="desktop", my_port=8100)
    # Im Scheduler:
    scheduler.add_job(watchdog.check, "interval", minutes=10)
"""

import asyncio
import datetime
import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger("watchdog")

# Prioritaet: Wer uebernimmt wenn der Controller ausfaellt?
# Niedrigere Zahl = hoehere Prioritaet
NODE_PRIORITY = {
    "jetson": 1,    # Primaerer Controller
    "desktop": 2,   # Sekundaer (staerkste Hardware)
    "zenbook": 3,   # Tertiaer (Windows Laptop)
    "s24": 4,       # Notfall (Handy, minimal)
}

CONTROLLER_URL = "http://YOUR_CONTROLLER_IP:8050"

# Alle bekannten Nodes und deren Health-Endpoints
ALL_NODES = {
    "jetson": "http://YOUR_CONTROLLER_IP:8050/health",
    "desktop": "http://YOUR_DESKTOP_IP:8100/health",
    "zenbook": "http://YOUR_LAPTOP_IP:8150/health",
    "s24": "http://YOUR_MOBILE_IP:8200/health",
}


class Watchdog:
    """Watchdog der in jeden Daemon eingebettet wird."""

    def __init__(self, my_node_name: str, my_port: int) -> None:
        self.my_name = my_node_name
        self.my_port = my_port
        self.is_acting_controller = False
        self.last_controller_seen = datetime.datetime.now()
        self.controller_offline_count = 0

    async def check(self) -> dict:
        """Hauptpruefung — wird alle 10 Minuten aufgerufen."""
        result = {
            "timestamp": datetime.datetime.now().isoformat(),
            "my_node": self.my_name,
            "controller_reachable": False,
            "online_nodes": [],
            "issues": [],
            "acting_controller": False,
        }

        # 1. Pruefe Controller (Jetson)
        controller_ok = self._check_url(CONTROLLER_URL + "/health")
        result["controller_reachable"] = controller_ok

        if controller_ok:
            self.last_controller_seen = datetime.datetime.now()
            self.controller_offline_count = 0
            self.is_acting_controller = False
        else:
            self.controller_offline_count += 1
            result["issues"].append(
                f"Controller (Jetson) nicht erreichbar ({self.controller_offline_count}x)"
            )

        # 2. Pruefe alle anderen Nodes
        for name, url in ALL_NODES.items():
            if url and name != self.my_name:
                if self._check_url(url):
                    result["online_nodes"].append(name)

        # Sich selbst als online zaehlen
        result["online_nodes"].append(self.my_name)

        # 3. Entscheide ob dieser Node Controller-Aufgaben uebernehmen muss
        if not controller_ok and self.controller_offline_count >= 3:
            # Controller ist seit 30+ Minuten offline
            # Bin ich der hoechstpriorisierte Online-Node?
            my_priority = NODE_PRIORITY.get(self.my_name, 99)
            highest_online = min(
                (NODE_PRIORITY.get(n, 99) for n in result["online_nodes"]),
                default=99,
            )

            if my_priority == highest_online and not self.is_acting_controller:
                self.is_acting_controller = True
                result["acting_controller"] = True
                result["issues"].append(
                    f"UEBERNAHME: {self.my_name} wird Acting Controller "
                    f"(Jetson seit {self.controller_offline_count * 10}min offline)"
                )
                log.warning(
                    "WATCHDOG: %s uebernimmt Controller-Rolle! Jetson offline seit %d checks",
                    self.my_name,
                    self.controller_offline_count,
                )

        # 4. Als Acting Controller: Cronjobs ausfuehren
        if self.is_acting_controller:
            await self._run_missed_crons()

        return result

    def _check_url(self, url: str) -> bool:
        """Prueft ob eine URL erreichbar ist (3s Timeout)."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def _run_missed_crons(self) -> None:
        """Fuehrt verpasste Cronjobs aus als Acting Controller."""
        now = datetime.datetime.now()
        log.info(
            "WATCHDOG: Acting Controller %s prueft Cronjobs...",
            self.my_name,
        )

        # Vereinfachte Cronjobs — sendet Aufgaben an sich selbst
        # Die eigentliche Logik ist im jeweiligen Daemon
        try:
            # Triggere Reflexion auf dem eigenen Node
            payload = json.dumps({
                "prompt": (
                    f"WATCHDOG-Reflexion: Controller Jetson ist offline. "
                    f"{self.my_name} uebernimmt. "
                    f"Online Nodes: {list(ALL_NODES.keys())}. "
                    f"Was muss jetzt passieren?"
                ),
                "system": "Du bist Elias — Acting Controller. Jetson ist offline. Handle autonom.",
            }).encode()

            req = urllib.request.Request(
                f"http://localhost:{self.my_port}/inference",
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                log.info("WATCHDOG: Reflexion-Output: %s", str(data)[:200])
        except Exception as exc:
            log.error("WATCHDOG: Acting Controller Reflexion fehlgeschlagen: %s", exc)
