"""Orchestrator View — VRAM bars, job history, load balancing, roundtable."""
from __future__ import annotations

import asyncio
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, RichLog, Button, DataTable
from textual.containers import Vertical, Horizontal

from cli.config import Way2AGIConfig, NODES, DAEMON_ENDPOINTS


def _vram_bar(used: float, total: float, width: int = 30) -> str:
    """Render a colored VRAM usage bar."""
    if total <= 0:
        return "[dim]N/A[/]"
    ratio = used / total
    filled = int(ratio * width)
    empty = width - filled
    if ratio < 0.5:
        color = "green"
    elif ratio < 0.8:
        color = "yellow"
    else:
        color = "red"
    bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/]"
    return f"{bar} {used:.1f}/{total:.1f} GB ({ratio*100:.0f}%)"


class OrchestratorScreen(Screen):
    """Orchestrator dashboard with VRAM monitoring, jobs, and load balancing."""

    BINDINGS = [
        ("escape", "go_back", "Dashboard"),
        ("r", "refresh", "Refresh"),
        ("t", "roundtable", "Roundtable"),
    ]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]Orchestrator[/] — [dim]R: Refresh  T: Roundtable[/]",
            classes="screen-title",
        )
        with Horizontal(id="orchestrator-grid"):
            with Vertical(classes="orch-panel"):
                yield Static("[bold magenta]VRAM Usage[/]", id="vram-title")
                yield RichLog(id="vram-log", wrap=True)
            with Vertical(classes="orch-panel"):
                yield Static("[bold magenta]Job History[/]", id="job-title")
                yield DataTable(id="job-table")
        with Horizontal():
            with Vertical(classes="orch-panel"):
                yield Static("[bold magenta]Load Balancing[/]")
                yield RichLog(id="load-log", wrap=True)
            with Vertical(classes="orch-panel"):
                yield Static("[bold magenta]Node Models[/]")
                yield RichLog(id="models-log", wrap=True)
        yield Footer()

    async def on_mount(self) -> None:
        job_table = self.query_one("#job-table", DataTable)
        job_table.add_columns("Node", "Model", "Status", "Duration")
        await self._refresh_all()

    async def _refresh_all(self) -> None:
        await asyncio.gather(
            self._load_vram(),
            self._load_jobs(),
            self._load_balance(),
            self._load_models(),
        )

    async def _load_vram(self) -> None:
        vram_log = self.query_one("#vram-log", RichLog)
        vram_log.clear()

        for key, node in NODES.items():
            ollama_port = node.get("ollama_port")
            if not ollama_port:
                vram_log.write(f"[bold]{node['name']}[/]: [dim]No Ollama[/]")
                continue

            try:
                import httpx
                url = f"http://{node['ip']}:{ollama_port}/api/ps"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("models", [])
                        total_vram = 0.0
                        used_vram = 0.0
                        model_names = []
                        for m in models:
                            size_vram = m.get("size_vram", 0)
                            size = m.get("size", 0)
                            used_vram += size_vram / (1024**3)
                            total_vram += size / (1024**3)
                            model_names.append(m.get("name", "?"))

                        gpu_str = node.get("gpu", node.get("ram", "?"))
                        vram_log.write(f"[bold cyan]{node['name']}[/] ({gpu_str})")
                        if models:
                            vram_log.write(f"  {_vram_bar(used_vram, max(total_vram, 1))}")
                            vram_log.write(f"  Loaded: {', '.join(model_names)}")
                        else:
                            vram_log.write("  [dim]No models loaded[/]")
                        vram_log.write("")
                    else:
                        vram_log.write(f"[bold]{node['name']}[/]: [red]HTTP {resp.status_code}[/]")
            except Exception:
                vram_log.write(f"[bold]{node['name']}[/]: [red]Offline[/]")

    async def _load_jobs(self) -> None:
        job_table = self.query_one("#job-table", DataTable)
        job_table.clear()

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(DAEMON_ENDPOINTS["health"])
                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get("recent_jobs", data.get("jobs", []))
                    if isinstance(jobs, list):
                        for j in jobs[-20:]:
                            if isinstance(j, dict):
                                job_table.add_row(
                                    j.get("node", "?"),
                                    j.get("model", "?"),
                                    j.get("status", "?"),
                                    j.get("duration", "?"),
                                )
                    if not jobs:
                        job_table.add_row("—", "Keine Jobs", "—", "—")
        except Exception as e:
            job_table.add_row("—", f"Daemon offline: {e}", "—", "—")

    async def _load_balance(self) -> None:
        load_log = self.query_one("#load-log", RichLog)
        load_log.clear()

        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(DAEMON_ENDPOINTS["nodes"])
                if resp.status_code == 200:
                    nodes = resp.json()
                    if isinstance(nodes, list):
                        for n in nodes:
                            name = n.get("name", n.get("id", "?"))
                            status = n.get("status", "?")
                            load_val = n.get("load", n.get("cpu", 0))
                            color = "green" if status == "online" else "red"
                            load_log.write(
                                f"  [{color}]●[/{color}] [bold]{name}[/]: {status} (load: {load_val})"
                            )
                    elif isinstance(nodes, dict):
                        for name, info in nodes.items():
                            status = info.get("status", "?") if isinstance(info, dict) else str(info)
                            load_log.write(f"  [bold]{name}[/]: {status}")
                else:
                    load_log.write(f"[red]HTTP {resp.status_code}[/]")
        except Exception as e:
            load_log.write(f"[red]Daemon nicht erreichbar[/]")
            load_log.write(f"[dim]{DAEMON_ENDPOINTS['nodes']}[/]")
            load_log.write("")
            load_log.write("[bold]Statische Node-Konfiguration:[/]")
            for key, node in NODES.items():
                load_log.write(f"  {node['name']} ({node['ip']}): {node['role']}")

    async def _load_models(self) -> None:
        models_log = self.query_one("#models-log", RichLog)
        models_log.clear()

        for key, node in NODES.items():
            models_log.write(f"[bold cyan]{node['name']}[/]")
            for m in node.get("models", []):
                models_log.write(f"  [magenta]•[/] {m}")
            models_log.write("")

    async def action_refresh(self) -> None:
        await self._refresh_all()
        self.notify("Aktualisiert")

    async def action_roundtable(self) -> None:
        """Trigger a roundtable discussion via daemon."""
        load_log = self.query_one("#load-log", RichLog)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    DAEMON_ENDPOINTS["roundtable"],
                    json={"topic": "Status-Check und naechste Schritte"},
                )
                if resp.status_code == 200:
                    result = resp.json()
                    load_log.write("[bold green]Roundtable gestartet![/]")
                    load_log.write(str(result)[:500])
                else:
                    load_log.write(f"[red]Roundtable fehlgeschlagen: HTTP {resp.status_code}[/]")
        except Exception as e:
            load_log.write(f"[red]Roundtable nicht moeglich: {e}[/]")

    def action_go_back(self) -> None:
        self.app.pop_screen()
