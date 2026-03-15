#!/usr/bin/env python3
"""Way2AGI Agent Language (WAL) — Phase 1: Komprimierte Inter-Agent-Kommunikation."""
import sqlite3
import json
import re
from datetime import datetime

DB_PATH = "/opt/way2agi/memory/db/elias_memory.db"

# Phase 1: Befehlscodes
COMMANDS = {
    "CHK": "check/pruefe", "SVC": "service", "MEM": "memory_operation",
    "RST": "restart", "WOL": "wake_on_lan", "QRY": "query/abfrage",
    "STR": "store/speichere", "EVL": "evaluate/bewerte", "RPT": "report/bericht",
    "ERR": "error/fehler", "STA": "status", "UPD": "update",
    "DEL": "delegate", "FIX": "fix/repariere", "SCH": "schedule/plane",
    "TRN": "train", "SYN": "sync", "BKP": "backup",
    "WRN": "warning", "ACK": "acknowledge", "REQ": "request",
    "RES": "response", "LOG": "log_entry", "TSK": "task",
    "RUL": "rule_check", "GOL": "goal_check", "REF": "reflect",
    "CUR": "curiosity", "IDN": "identity", "CON": "consolidate",
    "PRI": "prioritize", "ESC": "escalate", "FLB": "fallback",
}

# Agenten-Kuerzel
AGENTS = {
    "NM": "NetworkManager", "OR": "Orchestrator", "MA": "MemoryAgent",
    "CA": "ConsciousnessAgent", "GG": "GoalGuard", "AL": "AgentLoop",
    "VA": "VerifiedAnswer", "WD": "Watchdog", "MO": "MicroOrchestrator",
}

def encode(sender: str, receiver: str, command: str, params: dict = None) -> str:
    """Kodiert eine Agent-Nachricht ins WAL-Format."""
    s = AGENTS.get(sender, sender)
    r = AGENTS.get(receiver, receiver)
    # Reverse lookup fuer sender/receiver Kuerzel
    s_code = next((k for k, v in AGENTS.items() if v == sender), sender)
    r_code = next((k for k, v in AGENTS.items() if v == receiver), receiver)
    param_str = ""
    if params:
        param_str = "|".join(f"{k}={v}" for k, v in params.items())
    return f"{s_code}>{r_code}:{command}({param_str})"

def decode(message: str) -> dict:
    """Dekodiert eine WAL-Nachricht in ein lesbares Dict."""
    match = re.match(r"(\w+)>(\w+):(\w+)\((.*)\)", message)
    if not match:
        return {"raw": message, "error": "parse_failed"}
    sender, receiver, command, params_str = match.groups()
    params = {}
    if params_str:
        for p in params_str.split("|"):
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = v
    return {
        "sender": AGENTS.get(sender, sender),
        "receiver": AGENTS.get(receiver, receiver),
        "command": COMMANDS.get(command, command),
        "command_code": command,
        "params": params,
    }

def log_message(message: str, decoded: dict = None):
    """Loggt eine WAL-Nachricht in die DB."""
    if not decoded:
        decoded = decode(message)
    try:
        db = sqlite3.connect(DB_PATH, timeout=30)
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA busy_timeout = 5000;")
        db.execute("CREATE TABLE IF NOT EXISTS agent_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, sender TEXT, receiver TEXT, command TEXT, params TEXT, timestamp TEXT)")
        db.execute("INSERT INTO agent_messages (message, sender, receiver, command, params, timestamp) VALUES (?,?,?,?,?,?)",
            (message, decoded.get("sender",""), decoded.get("receiver",""), decoded.get("command_code",""), json.dumps(decoded.get("params",{})), datetime.now().isoformat()))
        db.commit()
        db.close()
    except Exception as e:
        pass  # Non-blocking

# Convenience-Funktionen fuer haeufige Nachrichten
def nm_report_node(node: str, status: str, latency: int = 0):
    return encode("NM", "OR", "STA", {"node": node, "status": status, "ms": str(latency)})

def or_delegate_task(task_id: str, target: str, model: str = "auto"):
    return encode("OR", "AL", "DEL", {"task": task_id, "target": target, "model": model})

def ma_store(key: str, value: str, mtype: str = "episodic"):
    return encode("MA", "MA", "STR", {"key": key, "val": value[:100], "type": mtype})

def gg_rule_violation(rule: str, details: str):
    return encode("GG", "OR", "ERR", {"rule": rule, "details": details[:100]})

def ca_reflect(topic: str, confidence: str):
    return encode("CA", "MA", "REF", {"topic": topic, "conf": confidence})

if __name__ == "__main__":
    # Demo
    msgs = [
        nm_report_node("desktop", "up", 16),
        or_delegate_task("T001", "desktop", "nemotron-3-super"),
        ma_store("session_context", "Training laeuft auf RTX 5090"),
        gg_rule_violation("R008", "Fehler wiederholt: DB-Pfad falsch"),
        ca_reflect("guardrails", "0.85"),
    ]
    for m in msgs:
        print(f"WAL: {m}")
        print(f"  → {decode(m)}")
        log_message(m)
    print(f"\n{len(msgs)} Nachrichten geloggt")

# =============================================================================
# SHORTCUTS — Ultra-kompakte Inter-Agent-Kommunikation
# Jeder spart 10-50 Tokens pro Nachricht x hunderte Male pro Stunde
# =============================================================================

SHORTCUTS = {
    # Node Status (haeufigste: 420x/2h)
    "D+": "desktop online",
    "D-": "desktop offline",
    "D+16": "desktop online 16ms",
    "J+": "inference-node online",
    "J-": "inference-node offline",
    "J+7": "inference-node online 7ms",
    "S+": "mobile-node online",
    "M-": "mobile offline",

    # Task Status (haeufigste: 685x/2h)
    "+T": "task gestartet",
    "VT": "task fertig",
    "XT": "task fehler",
    "S1": "schritt 1", "S2": "schritt 2", "S3": "schritt 3",
    "S4": "schritt 4", "S5": "schritt 5",

    # Agent-zu-Agent (haeufigste: 1272x/2h)
    "O?": "orchestrator anfrage",
    "O!": "orchestrator antwort ok",
    "OX": "orchestrator fehler",
    "M?": "memory query",
    "M!": "memory gespeichert",
    "G?": "goalguard pruefung",
    "G!": "goalguard ok",
    "GX": "goalguard verletzung",
    "N?": "networkmanager check",
    "N!": "alle nodes ok",
    "NX": "node ausgefallen",
    "C?": "consciousness reflect",
    "C!": "confidence ok",

    # System (20x/2h)
    "$?": "ssd backup check",
    "$!": "ssd backup ok",
    "W!": "wol gesendet",
    "R!": "service neugestartet",
    "B!": "db sync ok",

    # Einzeichen-Sofort
    "?": "status aller systeme",
    "!": "alles ok",
    "X": "fehler aufgetreten",
}

# Node-Kuerzel fuer dynamische Shortcuts
_NODE_MAP = {"desktop": "D", "inference-node": "J", "mobile-node": "S", "s24": "M", "npu-node": "Z"}
_NODE_MAP_REV = {v: k for k, v in _NODE_MAP.items()}


def shortcut_encode(msg: str) -> str:
    """Komprimiert eine Agent-Nachricht zu einem Shortcut wenn moeglich."""
    msg_lower = msg.lower()
    # Exakte Matches (laengste zuerst fuer Praezision)
    for short, full in sorted(SHORTCUTS.items(), key=lambda x: -len(x[1])):
        if full == msg_lower:
            return short
    # Pattern Matches
    for node, code in _NODE_MAP.items():
        if node in msg_lower:
            if "online" in msg_lower:
                return code + "+"
            if "offline" in msg_lower:
                return code + "-"
    if "task" in msg_lower and "fertig" in msg_lower:
        return "VT"
    if "task" in msg_lower and "gestartet" in msg_lower:
        return "+T"
    if "fehler" in msg_lower or "error" in msg_lower:
        return "X"
    return msg  # Kein Shortcut gefunden — Original behalten


def shortcut_decode(code: str) -> str:
    """Dekodiert einen Shortcut zurueck in natuerliche Sprache."""
    return SHORTCUTS.get(code, code)


def shortcut_node_status(node: str, online: bool, latency_ms: int = 0) -> str:
    """Erzeugt kompakten Node-Status-Shortcut: D+16, J-, etc."""
    code = _NODE_MAP.get(node, node[0].upper())
    status = "+" if online else "-"
    if online and latency_ms > 0:
        return "%s%s%d" % (code, status, latency_ms)
    return "%s%s" % (code, status)


def shortcut_task(task_id: str, event: str, extra: str = "") -> str:
    """Erzeugt kompakten Task-Shortcut: +T:T001, VT:T001:3S:45s, XT:T001"""
    prefix = {
        "start": "+T", "done": "VT", "error": "XT",
        "step": "S", "blocked": "XT",
    }.get(event, event)
    parts = [prefix]
    if task_id:
        parts[0] += ":" + task_id
    if extra:
        parts[0] += ":" + extra
    return parts[0]
