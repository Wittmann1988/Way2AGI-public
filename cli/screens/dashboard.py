"""Dashboard — Main screen with ASCII logo, node status, quick actions."""
from __future__ import annotations

import asyncio
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static, Footer
from textual.containers import Horizontal, Vertical

from cli.widgets.header import Way2AGIHeader
from cli.widgets.status import StatusPanel, NodeStatusGrid
from cli.config import Way2AGIConfig, NODES

ACTIONS_TEXT = """\
[bold cyan]Quick Actions[/]

  [bold magenta][C][/] Chat starten
  [bold magenta][P][/] Model Selection
  [bold magenta][S][/] Settings
  [bold magenta][M][/] Memory Browser
  [bold magenta][O][/] Orchestrator
  [bold magenta][Y][/] System Monitor
  [bold magenta][K][/] MCP Server
  [bold magenta][D][/] Diagnostics
  [bold magenta][Q][/] Beenden

[dim]━━━━━━━━━━━━━━━━━━━━━━━[/]
[dim]Way2AGI v2.0 · Elias[/]"""


class DashboardScreen(Screen):
    """Main dashboard with status, node grid, and quick actions."""

    BINDINGS = [
        ("c", "open_chat", "Chat"),
        ("p", "open_models", "Models"),
        ("s", "open_settings", "Settings"),
        ("m", "open_memory", "Memory"),
        ("o", "open_orchestrator", "Orchestrator"),
        ("y", "open_sysmon", "SysMonitor"),
        ("k", "open_mcp", "MCP"),
        ("d", "open_diagnostics", "Diagnostics"),
        ("q", "quit", "Beenden"),
        ("r", "refresh_nodes", "Refresh"),
    ]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Way2AGIHeader()
        with Horizontal(id="dashboard-panels"):
            with Vertical():
                yield StatusPanel(self.config)
                yield NodeStatusGrid()
            yield Static(ACTIONS_TEXT, classes="actions-panel")
        yield Footer()

    async def on_mount(self) -> None:
        asyncio.create_task(self._check_nodes())

    async def _check_nodes(self) -> None:
        """Ping all nodes to check online status."""
        grid = self.query_one(NodeStatusGrid)
        for key, node in NODES.items():
            try:
                import httpx
                port = node.get("ollama_port", node.get("port", 8050))
                url = f"http://{node['ip']}:{port}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(url)
                    grid.set_status(key, resp.status_code < 500)
            except Exception:
                grid.set_status(key, False)

    def action_open_chat(self) -> None:
        self.app.push_screen("chat")

    def action_open_models(self) -> None:
        self.app.push_screen("models")

    def action_open_settings(self) -> None:
        self.app.push_screen("settings")

    def action_open_memory(self) -> None:
        self.app.push_screen("memory")

    def action_open_orchestrator(self) -> None:
        self.app.push_screen("orchestrator")

    def action_open_sysmon(self) -> None:
        self.app.push_screen("sysmon")

    def action_open_mcp(self) -> None:
        self.app.push_screen("mcp")

    def action_open_diagnostics(self) -> None:
        self.app.push_screen("diagnostics")

    async def action_refresh_nodes(self) -> None:
        await self._check_nodes()

    def action_quit(self) -> None:
        self.app.exit()
