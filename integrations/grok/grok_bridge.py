#!/usr/bin/env python3
"""
Grok Bridge — xAI Grok als Ressource fuer Way2AGI.

Zwei Modi:
1. API-Modus (primaer): Direkt via api.x.ai (OpenAI-kompatibel)
2. Tasker-Modus (Fallback): Via Notification → Grok App → Callback (kein Limit)

Usage:
  python grok_bridge.py "Erklaere Speculative Decoding"
  python grok_bridge.py --mode api "Was ist IMGEP?"
  python grok_bridge.py --mode tasker "Analysiere diesen Code"
  python grok_bridge.py --roundtable "Consciousness Agent Design"
  python grok_bridge.py --interactive
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# --- Config ---
XAI_API_URL = "https://api.x.ai/v1/chat/completions"
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
DEFAULT_MODEL = "grok-4.2"

BRIDGE_DIR = Path(os.environ.get("GROK_BRIDGE_DIR", os.path.expanduser("~/grok-bridge")))
REQUEST_FILE = BRIDGE_DIR / "request.txt"
RESPONSE_FILE = BRIDGE_DIR / "response.json"
HISTORY_DIR = BRIDGE_DIR / "history"
LOCK_FILE = BRIDGE_DIR / ".lock"

TASKER_TIMEOUT = 300  # 5 Min fuer Tasker-Modus
API_TIMEOUT = 120     # 2 Min fuer API


def setup():
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# API-Modus (primaer) — Direkt via api.x.ai
# ============================================================

def query_api(prompt: str, system: str = "", model: str = DEFAULT_MODEL,
              temperature: float = 0.7, max_tokens: int = 4096) -> str | None:
    """Query Grok via xAI API (OpenAI-kompatibel)."""
    if not XAI_API_KEY:
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        XAI_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {XAI_API_KEY}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=API_TIMEOUT)
        data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        _save_history("api", prompt, content, model)
        return content
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"[API ERROR] {e.code}: {body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[API ERROR] {e}", file=sys.stderr)
        return None


# ============================================================
# Tasker-Modus (Fallback) — Kein Limit, via App
# ============================================================

def query_tasker(prompt: str, timeout: int = TASKER_TIMEOUT) -> str | None:
    """Query Grok via Tasker-Bridge (Notification → App → Callback)."""
    setup()
    request_id = f"grok-{int(time.time())}"

    # Lock pruefen
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age > 120:
            LOCK_FILE.unlink()
        else:
            print(f"[WARN] Request laeuft ({age:.0f}s)", file=sys.stderr)

    # Cleanup
    RESPONSE_FILE.unlink(missing_ok=True)

    # Request schreiben (Plain-Text fuer Tasker stdout)
    REQUEST_FILE.write_text(prompt)
    # JSON-Metadata separat (fuer History/Tracking)
    meta = {"id": request_id, "prompt": prompt, "timestamp": time.time()}
    (BRIDGE_DIR / "request_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))
    LOCK_FILE.touch()

    # Prompt auch ins Clipboard fuer einfaches Pasten
    try:
        subprocess.run(
            ["termux-clipboard-set", prompt],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass

    # Notification als Tasker-Trigger
    try:
        subprocess.run([
            "termux-notification",
            "--title", "GROK_REQUEST",
            "--content", prompt[:120],
            "--id", "grok-bridge",
            "--group", "grok",
            "--button1", "Prompt kopiert",
            "--button1-action", f"termux-clipboard-set '{prompt[:500]}'",
        ], capture_output=True, timeout=10)
    except Exception:
        pass

    print(f"[SENT] Warte auf Grok-Antwort... (Prompt im Clipboard)")

    # Warten auf Response
    start = time.time()
    while time.time() - start < timeout:
        if RESPONSE_FILE.exists():
            try:
                data = json.loads(RESPONSE_FILE.read_text())
                response = data.get("response", "")
                if response:
                    LOCK_FILE.unlink(missing_ok=True)
                    _save_history("tasker", prompt, response, "grok-app")
                    return response
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(2)

    LOCK_FILE.unlink(missing_ok=True)
    print(f"[TIMEOUT] {timeout}s", file=sys.stderr)
    return None


# ============================================================
# Auto-Modus: API first, Tasker als Fallback
# ============================================================

def query_grok(prompt: str, system: str = "", mode: str = "auto",
               model: str = DEFAULT_MODEL) -> str | None:
    """Query Grok — versucht API, faellt auf Tasker zurueck."""
    if mode == "api" or (mode == "auto" and XAI_API_KEY):
        result = query_api(prompt, system, model)
        if result:
            return result
        if mode == "api":
            return None
        print("[INFO] API fehlgeschlagen, Tasker-Fallback...", file=sys.stderr)

    if mode in ("tasker", "auto"):
        return query_tasker(prompt)

    return None


# ============================================================
# Roundtable-Integration
# ============================================================

def roundtable_query(topic: str, model: str = DEFAULT_MODEL) -> str | None:
    """Grok als Roundtable-Teilnehmer."""
    system = (
        "Du bist Grok, ein Teilnehmer am Way2AGI Roundtable. "
        "Sei direkt, kritisch und konkret. Nenne was die anderen Modelle "
        "uebersehen haben. Gib praktische Vorschlaege, keine Theorie."
    )
    return query_grok(topic, system, model=model)


# ============================================================
# Helpers
# ============================================================

def _save_history(mode: str, prompt: str, response: str, model: str):
    setup()
    entry = {
        "mode": mode,
        "model": model,
        "prompt": prompt,
        "response": response,
        "timestamp": time.time(),
    }
    hist_file = HISTORY_DIR / f"grok-{int(time.time())}.json"
    hist_file.write_text(json.dumps(entry, ensure_ascii=False, indent=2))


def interactive_mode(mode: str = "auto"):
    print("=== Grok Bridge Interactive ===")
    print(f"Modus: {mode} | API Key: {'ja' if XAI_API_KEY else 'NEIN'}")
    print("Tippe Prompt, Enter senden. 'quit' beenden.\n")

    while True:
        try:
            prompt = input("Du: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt or prompt.lower() in ("quit", "exit", "q"):
            break

        response = query_grok(prompt, mode=mode)
        if response:
            print(f"\nGrok: {response}\n")
        else:
            print("\n[Keine Antwort]\n")


def main():
    parser = argparse.ArgumentParser(description="Grok Bridge fuer Way2AGI")
    parser.add_argument("prompt", nargs="?", help="Prompt an Grok")
    parser.add_argument("--mode", choices=["auto", "api", "tasker"], default="auto")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--system", default="", help="System-Prompt")
    parser.add_argument("--roundtable", metavar="TOPIC", help="Als Roundtable-Teilnehmer")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--file", help="Prompt aus Datei")
    args = parser.parse_args()

    if args.status:
        setup()
        print(f"API Key:    {'gesetzt' if XAI_API_KEY else 'NICHT gesetzt (export XAI_API_KEY=...)'}")
        print(f"API URL:    {XAI_API_URL}")
        print(f"Model:      {DEFAULT_MODEL}")
        print(f"Bridge Dir: {BRIDGE_DIR}")
        print(f"Lock:       {'JA' if LOCK_FILE.exists() else 'Nein'}")
        hist = len(list(HISTORY_DIR.glob("*.json"))) if HISTORY_DIR.exists() else 0
        print(f"History:    {hist} Requests")
        return

    if args.interactive:
        interactive_mode(args.mode)
        return

    if args.roundtable:
        resp = roundtable_query(args.roundtable, args.model)
        if resp:
            print(resp)
        return

    prompt = args.prompt
    if args.file:
        prompt = Path(args.file).read_text().strip()

    if not prompt:
        parser.print_help()
        return

    response = query_grok(prompt, args.system, args.mode, args.model)
    if response:
        print(response)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
