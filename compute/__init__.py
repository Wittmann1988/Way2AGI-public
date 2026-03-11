"""
Way2AGI Compute Network — Verteilte Daemon-Architektur.

4-fache Redundanz: Jetson (Controller) + Desktop (Heavy) + Zenbook (NPU) + S24 (Light)
Jeder Node hat: Awareness (Regeln, TODOs), Watchdog (Uebernahme), Daemon (API).

Nodes:
    jetson_daemon.py   — Port 8050, Controller, Memory, GoalGuard, Cronjobs
    desktop_daemon.py  — Port 8100, YOUR_GPU, VRAM-Manager, 21 Modelle
    laptop_daemon.py   — Port 8150, Phi Silica NPU, Light Inference
    s24_daemon.py      — Port 8200, qwen3:1.7b, Triage/Classification

Shared:
    shared_watchdog.py  — Jeder Node ueberwacht den Controller
    node_awareness.py   — Regeln, TODOs, Selbstverwaltung
"""
