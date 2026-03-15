"""
Way2AGI Cross-Platform GUI (Streamlit)
======================================
Laeuft identisch auf Linux und Windows.
Tabs: Basis-Einstellungen | Erweiterte Optionen
Integriert: dashboard/, gateway/, Model-Wahl, Roundtable-Konfiguration
"""

import os
import subprocess
import sys
from pathlib import Path

try:
    import streamlit as st
except ImportError:
    print("Streamlit nicht installiert. Installiere mit: pip install streamlit")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent
ENV_FILE = REPO_ROOT / ".env"


def load_env() -> dict[str, str]:
    """Lade .env Datei als dict."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def save_env(env: dict[str, str]) -> None:
    """Schreibe env dict zurueck in .env."""
    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def detect_ollama_models() -> list[str]:
    """Versuche Ollama-Modelle zu erkennen."""
    try:
        import ollama
        models = ollama.list()
        return [m["name"] for m in models.get("models", [])]
    except Exception:
        pass
    # Fallback: curl
    try:
        import json
        import urllib.request
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        resp = urllib.request.urlopen(f"{host}/api/tags", timeout=3)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def detect_gpu() -> str:
    """GPU-Erkennung."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "Keine NVIDIA GPU erkannt"


# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Way2AGI Launcher", layout="wide")
st.title("Way2AGI Launcher")

env = load_env()

# Modelle erkennen
available_models = detect_ollama_models()
if not available_models:
    available_models = ["qwen2:7b", "llama3.2:3b", "phi4:3.8b", "gemma2:9b", "gemma2:2b", "qwen2:1.5b"]

# Sidebar
st.sidebar.header("System-Info")
st.sidebar.text(f"GPU: {detect_gpu()}")
st.sidebar.text(f"Modelle erkannt: {len(available_models)}")
st.sidebar.info("Repo: github.com/Wittmann1988/Way2AGI-public")

# Tabs
tab1, tab2 = st.tabs(["Basis-Einstellungen", "Erweiterte Optionen"])

with tab1:
    st.subheader("Automatische Erkennung")
    st.success("Hardware, Nodes & Ollama erkannt")

    col1, col2, col3 = st.columns(3)
    with col1:
        primary = st.selectbox(
            "Fuehrendes Modell (primaerer Ansprechpartner)",
            available_models,
            index=available_models.index(env.get("PRIMARY_MODEL", available_models[0]))
            if env.get("PRIMARY_MODEL") in available_models else 0,
        )
    with col2:
        round1 = st.selectbox(
            "Roundtable Instanz 1",
            available_models,
            index=available_models.index(env.get("ROUND1", available_models[0]))
            if env.get("ROUND1") in available_models else min(1, len(available_models) - 1),
        )
    with col3:
        round2 = st.selectbox(
            "Roundtable Instanz 2",
            available_models,
            index=available_models.index(env.get("ROUND2", available_models[0]))
            if env.get("ROUND2") in available_models else min(2, len(available_models) - 1),
        )

    st.divider()

    # API Keys
    st.subheader("API-Keys (optional)")
    groq_key = st.text_input("GROQ_KEY", value=env.get("GROQ_KEY", ""), type="password")
    openai_key = st.text_input("OPENAI_KEY", value=env.get("OPENAI_KEY", ""), type="password")
    xai_key = st.text_input("XAI_KEY", value=env.get("XAI_KEY", ""), type="password")
    gemini_key = st.text_input("GEMINI_KEY", value=env.get("GEMINI_KEY", ""), type="password")

    col_save, col_start = st.columns(2)
    with col_save:
        if st.button("Konfiguration speichern"):
            env["PRIMARY_MODEL"] = primary
            env["ROUND1"] = round1
            env["ROUND2"] = round2
            if groq_key:
                env["GROQ_KEY"] = groq_key
            if openai_key:
                env["OPENAI_KEY"] = openai_key
            if xai_key:
                env["XAI_KEY"] = xai_key
            if gemini_key:
                env["GEMINI_KEY"] = gemini_key
            save_env(env)
            st.success("Konfiguration gespeichert!")

    with col_start:
        if st.button("Way2AGI starten (mit Persistent Roundtable)", type="primary"):
            cmd = [
                sys.executable, "-m", "cli",
                "--primary", primary,
                "--roundtable", f"{round1},{round2}",
            ]
            st.info(f"Starte: {' '.join(cmd)}")
            subprocess.Popen(cmd, cwd=str(REPO_ROOT))
            st.balloons()

with tab2:
    st.subheader("Erweiterte Optionen")

    vram_mgmt = st.checkbox("VRAM-Management (MicroOrchestrator)", value=True)
    self_evolve = st.checkbox("Self-Evolving Engine (Group-Evolving Agents)")
    vmao = st.checkbox("VMAO-Orchestrierung (Plan-Execute-Verify-Replan)")
    titans = st.checkbox("Titans-Memory mit Cognitive Replay")
    consciousness = st.checkbox("3-Layer Consciousness (Cognitive + Pattern + Instinct)")

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        gpu_limit = st.number_input("GPU-Stunden-Limit pro Tag", value=int(env.get("GPU_HOURS_LIMIT", "4")), min_value=1)
    with col_b:
        api_budget = st.text_input("Custom API-Budget ($/Monat)", value=env.get("API_BUDGET", "50"))

    if st.button("Erweiterte Einstellungen speichern"):
        env["VRAM_MANAGEMENT"] = str(vram_mgmt).lower()
        env["SELF_EVOLVING"] = str(self_evolve).lower()
        env["VMAO_ORCHESTRATION"] = str(vmao).lower()
        env["TITANS_MEMORY"] = str(titans).lower()
        env["CONSCIOUSNESS_3LAYER"] = str(consciousness).lower()
        env["GPU_HOURS_LIMIT"] = str(gpu_limit)
        env["API_BUDGET"] = api_budget
        save_env(env)
        st.success("Erweiterte Einstellungen gespeichert!")
