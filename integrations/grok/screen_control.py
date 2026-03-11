#!/usr/bin/env python3
"""
Screen Control — Screenshots und UI-Eingaben via Shizuku.

Erlaubt Elias, Apps auf dem Tablet zu steuern (Grok, Browser, etc.)

Usage:
  from screen_control import screenshot, tap, type_text, swipe, open_app

  img_path = screenshot()           # Screenshot machen
  tap(500, 300)                     # Tippen auf Koordinaten
  type_text("Hallo Grok")           # Text eingeben
  swipe(500, 800, 500, 200)         # Wischen
  open_app("ai.x.grok")            # App oeffnen
"""

import os
import subprocess
import time
from pathlib import Path

SCREENSHOT_DIR = Path(os.path.expanduser("~/screenshots"))
SDCARD_TMP = "/sdcard/elias_screenshot.png"


def _shizuku_exec(cmd: str) -> tuple[str, int]:
    """Fuehre Befehl via Shizuku aus."""
    result = subprocess.run(
        ["shizuku", "exec", cmd],
        capture_output=True, text=True, timeout=15,
    )
    # Filter bekannte harmlose Fehler
    stderr = "\n".join(
        l for l in result.stderr.splitlines()
        if "runListPackages" not in l
    )
    return result.stdout + stderr, result.returncode


def _direct_exec(cmd: str) -> tuple[str, int]:
    """Fuehre Befehl direkt aus (Fallback)."""
    result = subprocess.run(
        cmd.split(), capture_output=True, text=True, timeout=15,
    )
    return result.stdout + result.stderr, result.returncode


def _run(cmd: str) -> tuple[str, int]:
    """Versuche Shizuku, dann direkt."""
    try:
        out, code = _shizuku_exec(cmd)
        return out, code
    except Exception:
        pass
    try:
        out, code = _direct_exec(cmd)
        return out, code
    except Exception as e:
        return str(e), 1


def screenshot(resize: bool = True) -> str | None:
    """Mache Screenshot, speichere lokal, gib Pfad zurueck."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    local_path = SCREENSHOT_DIR / f"screen_{timestamp}.png"

    # Screenshot via Shizuku auf sdcard
    out, code = _run(f"screencap -p {SDCARD_TMP}")

    # Kopiere in Termux-Zugriff
    try:
        import shutil
        shutil.copy2(SDCARD_TMP, str(local_path))
    except Exception:
        subprocess.run(["cp", SDCARD_TMP, str(local_path)], capture_output=True)

    if not local_path.exists() or local_path.stat().st_size < 1000:
        return None

    # Resize fuer Claude Vision (max 2000x2000)
    if resize:
        try:
            from PIL import Image
            img = Image.open(str(local_path))
            if img.width > 2000 or img.height > 2000:
                ratio = min(2000 / img.width, 2000 / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                img.save(str(local_path))
        except ImportError:
            pass

    return str(local_path)


def tap(x: int, y: int) -> bool:
    """Tippe auf Bildschirmkoordinaten."""
    out, code = _run(f"input tap {x} {y}")
    return code == 0


def type_text(text: str) -> bool:
    """Gebe Text ein (in aktuell fokussiertes Feld)."""
    # Ersetze Leerzeichen fuer input command
    escaped = text.replace(" ", "%s").replace("&", "\\&").replace(";", "\\;")
    out, code = _run(f"input text {escaped}")
    return code == 0


def key_event(keycode: str) -> bool:
    """Sende Key Event (ENTER, BACK, HOME, etc.)."""
    out, code = _run(f"input keyevent {keycode}")
    return code == 0


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
    """Wisch-Geste."""
    out, code = _run(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
    return code == 0


def open_app(package: str, activity: str = "") -> bool:
    """Oeffne eine App."""
    if activity:
        cmd = f"am start -n {package}/{activity}"
    else:
        cmd = f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
    out, code = _run(cmd)
    return code == 0


def open_grok() -> bool:
    """Oeffne Grok App."""
    return open_app("ai.x.grok")


def paste_from_clipboard() -> bool:
    """Paste aus Clipboard (Ctrl+V Equivalent)."""
    # Setze erst Clipboard via termux-api, dann paste via keyevent
    return key_event("279")  # KEYCODE_PASTE


def set_clipboard(text: str) -> bool:
    """Setze Clipboard-Inhalt."""
    try:
        result = subprocess.run(
            ["termux-clipboard-set", text],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_screen_size() -> tuple[int, int] | None:
    """Hole Bildschirmgroesse."""
    out, code = _run("wm size")
    if "Physical size:" in out:
        size = out.split("Physical size:")[-1].strip()
        w, h = size.split("x")
        return int(w), int(h)
    return None


# ============================================================
# Grok-spezifische Funktionen
# ============================================================

def tasker_task(task_name: str) -> bool:
    """Rufe einen Tasker-Task auf."""
    try:
        result = subprocess.run(
            ["am", "broadcast",
             "-a", "net.dinglisch.android.taskerm.ACTION_TASK",
             "-es", "task_name", task_name],
            capture_output=True, text=True, timeout=10,
        )
        return "Broadcast sent" in (result.stdout + result.stderr)
    except Exception:
        return False


def grok_query(prompt: str, wait_seconds: int = 30) -> str | None:
    """
    Sende Query an Grok App und mache Screenshot der Antwort.

    1. Clipboard setzen
    2. Grok App oeffnen
    3. Ins Textfeld tippen
    4. Text einfuegen (Paste)
    5. Tasker "Enter" Task druecken
    6. Warten auf Antwort
    7. Screenshot der Antwort
    """
    # Clipboard setzen
    set_clipboard(prompt)
    time.sleep(0.5)

    # Grok oeffnen
    open_grok()
    time.sleep(3)

    # Paste aus Clipboard
    paste_from_clipboard()
    time.sleep(1)

    # Enter/Send via Tasker
    tasker_task("Enter")
    time.sleep(wait_seconds)

    # Screenshot der Antwort
    return screenshot()


def grok_scroll_and_read(screenshots: int = 3) -> list[str]:
    """Scrolle durch Grok-Antwort und mache mehrere Screenshots."""
    paths = []
    for i in range(screenshots):
        path = screenshot()
        if path:
            paths.append(path)
        # Nach unten scrollen
        size = get_screen_size()
        if size:
            w, h = size
            swipe(w // 2, h * 3 // 4, w // 2, h // 4, 500)
        time.sleep(1)
    return paths


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("=== Screen Control Test ===")
        size = get_screen_size()
        print(f"Screen: {size}")
        path = screenshot()
        print(f"Screenshot: {path}")
    elif len(sys.argv) > 1 and sys.argv[1] == "grok":
        prompt = " ".join(sys.argv[2:]) or "Test"
        print(f"Grok Query: {prompt}")
        path = grok_query(prompt)
        print(f"Screenshot: {path}")
    else:
        print("Usage: screen_control.py test|grok <prompt>")
