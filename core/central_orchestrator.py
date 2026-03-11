# core/central_orchestrator.py
"""
Central Orchestrator — Fragt die Micro-Orchestratoren
======================================================
Statt hardcodierter model_map fragt der zentrale Orchestrator
alle Geraete: "Wer kann diesen Task am besten?"

Jedes Geraet antwortet mit einem Bid (Modell, Speed, Confidence).
Der Central Orchestrator waehlt den besten Bid und delegiert.

Vorteile:
- Kein hardcoded Wissen ueber Modelle auf anderen Geraeten
- Neue Modelle werden automatisch entdeckt
- Failover: Wenn ein Geraet ausfaellt, bieten die anderen
- Dezentral: Geraete entscheiden selbst welches Modell sie nutzen
"""

import asyncio
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.central_orch")


@dataclass
class DeviceNode:
    """A device running a Micro-Orchestrator."""
    name: str
    ip: str
    port: int
    status: str = "unknown"     # up | down | unknown
    last_seen: float = 0.0
    capabilities: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Bid:
    """A bid from a device to handle a task."""
    device: str
    can_handle: bool
    model: str
    speed: float
    latency_ms: int
    confidence: float
    backend: str
    reason: str


class CentralOrchestrator:
    """
    Coordinates task execution across multiple devices.
    Each device runs a MicroOrchestrator that bids on tasks.
    """

    def __init__(self):
        self.devices: Dict[str, DeviceNode] = {}
        self._started_at = time.time()

    def register_device(self, name: str, ip: str, port: int):
        """Register a device with its Micro-Orchestrator endpoint."""
        self.devices[name] = DeviceNode(name=name, ip=ip, port=port)
        log.info("Device registriert: %s (%s:%d)", name, ip, port)

    def register_from_env(self):
        """Register devices from environment variables."""
        import os
        device_defs = [
            ("controller", "CONTROLLER_IP", 8050),
            ("desktop", "DESKTOP_IP", 8100),
            ("laptop", "LAPTOP_IP", 8150),
            ("mobile", "MOBILE_IP", 8200),
        ]
        for name, env_key, port in device_defs:
            ip = os.environ.get(env_key)
            if ip:
                self.register_device(name, ip, port)

    # --- Health + Discovery ---

    async def check_all_devices(self) -> Dict[str, str]:
        """Check health of all registered devices."""
        results = {}
        for name, device in self.devices.items():
            try:
                url = f"http://{device.ip}:{device.port}/health"
                req = urllib.request.Request(url, method="GET")
                resp = urllib.request.urlopen(req, timeout=5)
                data = json.loads(resp.read())
                device.status = data.get("status", "ok")
                device.last_seen = time.time()
                results[name] = device.status
            except Exception:
                device.status = "down"
                results[name] = "down"
        return results

    async def discover_all_capabilities(self) -> Dict[str, Any]:
        """Ask all devices for their capabilities."""
        all_caps = {}
        for name, device in self.devices.items():
            if device.status == "down":
                continue
            try:
                url = f"http://{device.ip}:{device.port}/capabilities"
                req = urllib.request.Request(url, method="GET")
                resp = urllib.request.urlopen(req, timeout=5)
                caps = json.loads(resp.read())
                device.capabilities = caps
                all_caps[name] = caps
            except Exception as e:
                log.debug("Capabilities von %s fehlgeschlagen: %s", name, e)
        return all_caps

    # --- Task Orchestration ---

    async def orchestrate(self, task: str, strategy: str = "auto") -> Dict[str, Any]:
        """
        Main orchestration: collect bids, pick best, execute.

        1. Send task to all active devices for bidding
        2. Collect bids (who can do it, how fast, how confident)
        3. Pick the best bid
        4. Execute on that device
        5. Return result
        """
        t0 = time.time()
        traces = []

        # 1. Collect bids from all active devices
        bids = await self._collect_bids(task)
        traces.append({
            "step": "collect_bids",
            "bids": len(bids),
            "devices_asked": len([d for d in self.devices.values() if d.status != "down"]),
        })

        if not bids:
            return {
                "result": "Fehler: Kein Geraet kann diesen Task bearbeiten",
                "routing": {"strategy": strategy},
                "duration_s": round(time.time() - t0, 2),
                "traces": traces,
            }

        # 2. Pick the best bid
        best = self._pick_best_bid(bids, strategy)
        traces.append({
            "step": "pick_bid",
            "device": best.device,
            "model": best.model,
            "confidence": best.confidence,
            "speed": best.speed,
            "reason": best.reason,
        })

        log.info("Task delegiert an %s (%s, confidence=%.2f)",
                 best.device, best.model, best.confidence)

        # 3. Execute on the chosen device
        result = await self._execute_on_device(best.device, task)
        duration = round(time.time() - t0, 2)

        traces.append({
            "step": "execute",
            "device": best.device,
            "success": result.get("success", False),
            "duration_s": duration,
        })

        return {
            "result": result.get("response", result.get("error", "Keine Antwort")),
            "routing": {
                "device": best.device,
                "model": best.model,
                "strategy": strategy,
                "confidence": best.confidence,
                "backend": best.backend,
            },
            "duration_s": duration,
            "traces": traces,
        }

    async def _collect_bids(self, task: str) -> List[Bid]:
        """Ask all active devices to bid on a task."""
        bids = []
        payload = json.dumps({"task": task}).encode()

        for name, device in self.devices.items():
            if device.status == "down":
                continue
            try:
                url = f"http://{device.ip}:{device.port}/bid"
                req = urllib.request.Request(
                    url, data=payload, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                resp = urllib.request.urlopen(req, timeout=5)
                data = json.loads(resp.read())
                if data.get("can_handle"):
                    bids.append(Bid(
                        device=name,
                        can_handle=True,
                        model=data.get("model", ""),
                        speed=data.get("speed", 0),
                        latency_ms=data.get("latency_ms", 999),
                        confidence=data.get("confidence", 0),
                        backend=data.get("backend", "ollama"),
                        reason=data.get("reason", ""),
                    ))
            except Exception as e:
                log.debug("Bid von %s fehlgeschlagen: %s", name, e)

        log.info("Bids gesammelt: %d von %d Geraeten", len(bids), len(self.devices))
        return bids

    def _pick_best_bid(self, bids: List[Bid], strategy: str = "auto") -> Bid:
        """Pick the best bid based on strategy."""
        if not bids:
            raise ValueError("Keine Bids vorhanden")

        if strategy == "fastest":
            # Pick lowest latency
            return min(bids, key=lambda b: b.latency_ms)
        elif strategy == "smallest":
            # Pick highest speed (= smallest model)
            return max(bids, key=lambda b: b.speed)
        elif strategy == "best":
            # Pick highest confidence
            return max(bids, key=lambda b: b.confidence)
        else:
            # Auto: balance confidence and speed
            return max(bids, key=lambda b: b.confidence * 0.6 + (b.speed / 100) * 0.4)

    async def _execute_on_device(self, device_name: str, task: str) -> Dict[str, Any]:
        """Execute a task on a specific device."""
        device = self.devices.get(device_name)
        if not device:
            return {"error": f"Device {device_name} nicht gefunden", "success": False}

        payload = json.dumps({"task": task}).encode()
        try:
            url = f"http://{device.ip}:{device.port}/execute"
            req = urllib.request.Request(
                url, data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e), "success": False}

    # --- Status ---

    def get_status(self) -> Dict[str, Any]:
        """Get overview of all devices and their status."""
        devices = {}
        for name, d in self.devices.items():
            devices[name] = {
                "ip": d.ip,
                "port": d.port,
                "status": d.status,
                "last_seen": datetime.fromtimestamp(d.last_seen).isoformat() if d.last_seen else "never",
                "model_count": len(d.capabilities.get("models", [])),
            }
        return {
            "devices": devices,
            "active": sum(1 for d in self.devices.values() if d.status != "down"),
            "total": len(self.devices),
            "uptime_s": round(time.time() - self._started_at, 1),
        }
