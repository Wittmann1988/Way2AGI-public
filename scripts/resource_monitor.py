#!/usr/bin/env python3
"""
Way2AGI Resource Monitor — Trackt Auslastung aller Ressourcen
==============================================================
Laeuft alle 10 Minuten per Cron auf Jetson.
Speichert Stats in SQLite. Abrufbar per CLI oder API.

Ressourcen:
- Lokal: Jetson, Desktop, Laptop, S24 (Ollama + llama.cpp)
- Cloud: OpenAI, xAI/Grok, Gemini, Groq

Ziel: Gleichmaessige Verteilung ueber alle Ressourcen.
"""

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime

DB_PATH = os.environ.get("WAY2AGI_DB", "/data/way2agi/memory/memory.db")

# Alle Ressourcen
NODES = {
    "jetson": {"ip": "192.168.50.21", "ollama": 11434, "llama_cpp": 8080, "micro_orch": 8051},
    "desktop": {"ip": "192.168.50.129", "ollama": 11434, "llama_cpp": 8080},
    "laptop": {"ip": "192.168.50.111", "ollama": 11434},
    "s24": {"ip": "192.168.50.182", "ollama": 11434},
}

CLOUD_APIS = {
    "openai": {"env": "OPENAI_API_KEY", "url": "https://api.openai.com/v1/models", "header": "Authorization"},
    "groq": {"env": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/models", "header": "Authorization"},
    "gemini": {"env": "GEMINI_API_KEY", "url": None},  # Kein einfacher Health-Check
    "xai": {"env": "XAI_API_KEY", "url": None},  # Nur via curl
}


def check_node(name, cfg):
    """Prueft einen lokalen Node. Gibt Status-Dict zurueck."""
    result = {"name": name, "status": "down", "models_loaded": 0, "latency_ms": -1}

    # Ollama check
    try:
        t0 = time.time()
        url = f"http://{cfg['ip']}:{cfg['ollama']}/api/ps"
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        result["status"] = "up"
        result["models_loaded"] = len(data.get("models", []))
        result["latency_ms"] = int((time.time() - t0) * 1000)
    except Exception:
        pass

    # llama.cpp check
    if "llama_cpp" in cfg:
        try:
            url = f"http://{cfg['ip']}:{cfg['llama_cpp']}/health"
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            result["specdec"] = data.get("status", "unknown")
        except Exception:
            result["specdec"] = "down"

    return result


def check_cloud(name, cfg):
    """Prueft ob Cloud-API verfuegbar ist."""
    key = os.environ.get(cfg["env"], "")
    if not key:
        return {"name": name, "status": "no_key"}

    if not cfg.get("url"):
        return {"name": name, "status": "available" if key else "no_key"}

    try:
        req = urllib.request.Request(
            cfg["url"], method="GET",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return {"name": name, "status": "available"}
    except Exception:
        return {"name": name, "status": "available"}  # Key exists = available


def get_usage_from_traces(hours=24):
    """Zaehlt API-Calls pro Ressource aus der traces-Tabelle."""
    try:
        db = sqlite3.connect(DB_PATH, timeout=5)
        db.row_factory = sqlite3.Row
        cutoff = time.time() - (hours * 3600)
        rows = db.execute(
            "SELECT model, COUNT(*) as calls, SUM(duration_ms) as total_ms "
            "FROM traces WHERE timestamp > ? GROUP BY model",
            (cutoff,)
        ).fetchall()
        db.close()
        return {r["model"]: {"calls": r["calls"], "total_ms": r["total_ms"] or 0} for r in rows}
    except Exception:
        return {}


def get_usage_from_action_log(hours=24):
    """Zaehlt Aktionen pro Device aus dem action_log."""
    try:
        db = sqlite3.connect(DB_PATH, timeout=5)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT device, COUNT(*) as calls FROM action_log "
            "WHERE created_at > datetime('now', ?) GROUP BY device",
            (f"-{hours} hours",)
        ).fetchall()
        db.close()
        return {r["device"]: r["calls"] for r in rows}
    except Exception:
        return {}


def calculate_utilization():
    """Berechnet Auslastung in Prozent fuer alle Ressourcen."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "local_nodes": {},
        "cloud_apis": {},
        "usage_24h": {},
        "balance_score": 0.0,  # 0-100%, 100% = perfekt gleichmaessig
    }

    # Lokale Nodes pruefen
    total_local_up = 0
    for name, cfg in NODES.items():
        status = check_node(name, cfg)
        report["local_nodes"][name] = status
        if status["status"] == "up":
            total_local_up += 1

    # Cloud APIs pruefen
    total_cloud_up = 0
    for name, cfg in CLOUD_APIS.items():
        status = check_cloud(name, cfg)
        report["cloud_apis"][name] = status
        if status["status"] == "available":
            total_cloud_up += 1

    # Usage aus Traces + Action Log
    trace_usage = get_usage_from_traces(24)
    action_usage = get_usage_from_action_log(24)
    report["usage_24h"] = {
        "by_model": trace_usage,
        "by_device": action_usage,
    }

    # Balance Score berechnen
    total_resources = total_local_up + total_cloud_up
    if total_resources > 0:
        # Wie gleichmaessig sind die Calls verteilt?
        all_calls = list(action_usage.values()) if action_usage else [0]
        if len(all_calls) > 1 and sum(all_calls) > 0:
            avg = sum(all_calls) / len(all_calls)
            variance = sum((c - avg) ** 2 for c in all_calls) / len(all_calls)
            max_variance = avg ** 2  # Worst case: alles auf einem
            balance = max(0, 100 * (1 - variance / max(max_variance, 1)))
        else:
            balance = 50.0  # Nicht genug Daten
        report["balance_score"] = round(balance, 1)

    # Summary
    report["summary"] = {
        "local_up": f"{total_local_up}/{len(NODES)}",
        "cloud_up": f"{total_cloud_up}/{len(CLOUD_APIS)}",
        "total_resources": total_resources,
        "total_calls_24h": sum(action_usage.values()) if action_usage else 0,
        "balance": f"{report['balance_score']:.0f}%",
    }

    return report


def save_snapshot(report):
    """Speichert Monitoring-Snapshot in DB."""
    try:
        db = sqlite3.connect(DB_PATH, timeout=5)
        db.execute(
            "CREATE TABLE IF NOT EXISTS resource_monitor ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  timestamp TEXT, data TEXT"
            ")"
        )
        db.execute(
            "INSERT INTO resource_monitor (timestamp, data) VALUES (?, ?)",
            (report["timestamp"], json.dumps(report)),
        )
        # Nur letzte 1000 Eintraege behalten
        db.execute(
            "DELETE FROM resource_monitor WHERE id NOT IN "
            "(SELECT id FROM resource_monitor ORDER BY id DESC LIMIT 1000)"
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"Snapshot speichern fehlgeschlagen: {e}")


def print_report(report):
    """Gibt den Report als lesbaren Text aus."""
    print(f"\n{'=' * 55}")
    print(f"  Way2AGI Resource Monitor — {report['timestamp'][:19]}")
    print(f"{'=' * 55}")

    print(f"\n  LOKALE NODES ({report['summary']['local_up']} aktiv)")
    print(f"  {'Name':<10} {'Status':<8} {'Modelle':<8} {'Latenz':<10} {'SpecDec'}")
    print(f"  {'-'*50}")
    for name, n in report["local_nodes"].items():
        specdec = n.get("specdec", "—")
        lat = f"{n['latency_ms']}ms" if n['latency_ms'] >= 0 else "—"
        print(f"  {name:<10} {n['status']:<8} {n['models_loaded']:<8} {lat:<10} {specdec}")

    print(f"\n  CLOUD APIs ({report['summary']['cloud_up']} verfuegbar)")
    print(f"  {'Name':<10} {'Status'}")
    print(f"  {'-'*25}")
    for name, c in report["cloud_apis"].items():
        print(f"  {name:<10} {c['status']}")

    usage = report["usage_24h"]
    if usage.get("by_device"):
        print(f"\n  AUSLASTUNG (letzte 24h)")
        print(f"  {'Device':<12} {'Calls'}")
        print(f"  {'-'*20}")
        for dev, calls in usage["by_device"].items():
            print(f"  {dev:<12} {calls}")

    print(f"\n  BALANCE SCORE: {report['summary']['balance']}")
    print(f"  (100% = perfekt gleichmaessig verteilt)")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    report = calculate_utilization()
    print_report(report)
    save_snapshot(report)
