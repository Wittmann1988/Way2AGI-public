"""System Monitor — CPU/RAM/GPU per node, logs, live refresh."""
from __future__ import annotations

import asyncio
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, RichLog
from textual.containers import Vertical, Horizontal

from cli.config import Way2AGIConfig, NODES


def _usage_bar(value: float, total: float, label: str, width: int = 25) -> str:
    """Render a colored usage bar with label."""
    if total <= 0:
        return f"  {label}: [dim]N/A[/]"
    ratio = value / total
    filled = int(ratio * width)
    empty = width - filled
    if ratio < 0.5:
        color = "green"
    elif ratio < 0.8:
        color = "yellow"
    else:
        color = "red"
    bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/]"
    return f"  {label}: {bar} {value:.1f}/{total:.1f} ({ratio*100:.0f}%)"


class SystemMonitorScreen(Screen):
    """System monitor with CPU/RAM/GPU per node and logs."""

    BINDINGS = [
        ("escape", "go_back", "Dashboard"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config
        self._auto_refresh_task = None

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]System Monitor[/] — [dim]R: Refresh[/]",
            classes="screen-title",
        )
        with Horizontal(id="sysmon-grid"):
            with Vertical(classes="sysmon-panel"):
                yield Static("[bold magenta]Node Resources[/]")
                yield RichLog(id="resources-log", wrap=True)
            with Vertical(classes="sysmon-panel"):
                yield Static("[bold magenta]System Logs[/]")
                yield RichLog(id="system-log", wrap=True)
        yield Footer()

    async def on_mount(self) -> None:
        await self._refresh_all()

    async def _refresh_all(self) -> None:
        await asyncio.gather(
            self._load_resources(),
            self._load_logs(),
        )

    async def _load_resources(self) -> None:
        log = self.query_one("#resources-log", RichLog)
        log.clear()

        # Local system info first
        log.write("[bold cyan]Local System (This Device)[/]")
        try:
            import os
            load1, load5, load15 = os.getloadavg()
            log.write(f"  Load: {load1:.2f} {load5:.2f} {load15:.2f}")
        except (OSError, AttributeError):
            log.write("  Load: [dim]N/A[/]")

        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        mem[key] = int(parts[1]) / (1024 * 1024)  # GB
                total = mem.get("MemTotal", 0)
                available = mem.get("MemAvailable", mem.get("MemFree", 0))
                used = total - available
                log.write(_usage_bar(used, total, "RAM (GB)"))
        except Exception:
            log.write("  RAM: [dim]N/A[/]")
        log.write("")

        # Remote nodes via Ollama API (lightweight check)
        for key, node in NODES.items():
            log.write(f"[bold cyan]{node['name']}[/] ({node['ip']})")

            # Check Ollama running models as proxy for GPU usage
            ollama_port = node.get("ollama_port")
            if ollama_port:
                try:
                    import httpx
                    url = f"http://{node['ip']}:{ollama_port}/api/ps"
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            data = resp.json()
                            models = data.get("models", [])
                            total_vram = 0.0
                            used_vram = 0.0
                            for m in models:
                                used_vram += m.get("size_vram", 0) / (1024**3)
                                total_vram += m.get("size", 0) / (1024**3)

                            if "gpu" in node:
                                log.write(f"  GPU: {node['gpu']}")
                            if "ram" in node:
                                log.write(f"  RAM: {node['ram']}")
                            if models:
                                log.write(_usage_bar(used_vram, max(total_vram, 1), "VRAM"))
                                log.write(f"  Models loaded: {len(models)}")
                            else:
                                log.write("  [dim]No models loaded[/]")
                            log.write(f"  [green]●[/] Ollama: Online")
                        else:
                            log.write(f"  [yellow]●[/] Ollama: HTTP {resp.status_code}")
                except Exception:
                    log.write(f"  [red]●[/] Ollama: Offline")
            else:
                log.write(f"  [dim]No Ollama configured[/]")

            # Check daemon port
            daemon_port = node.get("port")
            if daemon_port:
                try:
                    import httpx
                    url = f"http://{node['ip']}:{daemon_port}/health"
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            log.write(f"  [green]●[/] Daemon: Online (:{daemon_port})")
                        else:
                            log.write(f"  [yellow]●[/] Daemon: HTTP {resp.status_code}")
                except Exception:
                    log.write(f"  [red]●[/] Daemon: Offline (:{daemon_port})")

            log.write("")

    async def _load_logs(self) -> None:
        syslog = self.query_one("#system-log", RichLog)
        syslog.clear()

        syslog.write("[bold cyan]Recent Activity[/]\n")

        # Try to read Way2AGI action log from Jetson
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://YOUR_CONTROLLER_IP:8050/health")
                if resp.status_code == 200:
                    data = resp.json()
                    syslog.write(f"[green]●[/] Jetson Daemon: {data.get('status', 'online')}")
                    uptime = data.get("uptime", "?")
                    syslog.write(f"  Uptime: {uptime}")
                    version = data.get("version", "?")
                    syslog.write(f"  Version: {version}")
                    syslog.write("")

                    # Show any recent events
                    events = data.get("events", data.get("log", []))
                    if isinstance(events, list):
                        for ev in events[-10:]:
                            if isinstance(ev, dict):
                                syslog.write(f"  [{ev.get('level', 'info')}] {ev.get('message', ev)}")
                            else:
                                syslog.write(f"  {ev}")
        except Exception:
            syslog.write("[red]●[/] Jetson Daemon: Nicht erreichbar")

        syslog.write("")

        # Memory server status
        try:
            import httpx
            server_url = self.config.get("memory.server_url", "http://YOUR_CONTROLLER_IP:5555")
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{server_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    total = data.get("total_memories", data.get("memories", "?"))
                    syslog.write(f"[green]●[/] Memory Server: {total} memories")
                else:
                    syslog.write(f"[yellow]●[/] Memory Server: HTTP {resp.status_code}")
        except Exception:
            syslog.write("[red]●[/] Memory Server: Offline")

        syslog.write("")

        # Local Ollama status
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    syslog.write(f"[green]●[/] Local Ollama: {len(models)} models")
                else:
                    syslog.write("[yellow]●[/] Local Ollama: Running but no models")
        except Exception:
            syslog.write("[dim]●[/] Local Ollama: Not running")

        syslog.write("")
        syslog.write("[dim]Cronjobs (Jetson):[/]")
        syslog.write("  07:00 research.py — arXiv + GitHub")
        syslog.write("  08:00/14:00/20:00 goalguard.py — Regel-Pruefung")
        syslog.write("  12:00 roundtable.py — Multi-Model Discussion")
        syslog.write("  16:00 implement.py — Code Generation")
        syslog.write("  alle 5 Tage training.py — SFT/DPO on YOUR_GPU")

    async def action_refresh(self) -> None:
        await self._refresh_all()
        self.notify("Aktualisiert")

    def action_go_back(self) -> None:
        self.app.pop_screen()
