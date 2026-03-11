"""MCP Server Manager — Create, select, configure MCP servers."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, Input, Button, RichLog, Switch, Label
from textual.containers import Vertical, Horizontal, VerticalScroll

from cli.config import Way2AGIConfig


# Well-known MCP servers that can be auto-configured
KNOWN_MCP_SERVERS = {
    "sequential-thinking": {
        "description": "Chain-of-thought reasoning with sequential steps",
        "command": "node",
        "args": ["~/downloads/mcp-sequential-thinking/dist/index.js"],
        "default_active": True,
    },
    "memory": {
        "description": "Elias Memory — Knowledge Graph, Memories, Entities",
        "url": "http://YOUR_CONTROLLER_IP:5555",
        "default_active": True,
    },
    "ollama-sidekick": {
        "description": "Multi-model orchestration via local Ollama",
        "url": "http://YOUR_CONTROLLER_IP:11434",
        "default_active": True,
    },
    "network-agent": {
        "description": "Network diagnostics, WoL, SSH management",
        "command": "python3",
        "args": ["~/repos/Way2AGI/compute/network_agent.py"],
        "default_active": True,
    },
    "context7": {
        "description": "Documentation lookup for libraries and frameworks",
        "command": "npx",
        "args": ["-y", "@context7/mcp-server"],
        "default_active": False,
    },
    "hugging-face": {
        "description": "HuggingFace Hub — model search, paper search, spaces",
        "url": "https://huggingface.co",
        "default_active": False,
    },
    "gmail": {
        "description": "Gmail integration — read, search, draft emails",
        "url": "https://gmail.googleapis.com",
        "default_active": False,
    },
}


class MCPManagerScreen(Screen):
    """Manage MCP (Model Context Protocol) servers."""

    BINDINGS = [
        ("escape", "go_back", "Dashboard"),
        ("a", "add_server", "Neu"),
    ]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]MCP Server Manager[/] — [dim]A: Server hinzufuegen[/]",
            classes="screen-title",
        )
        with VerticalScroll():
            # Active servers from config
            yield Static("[bold magenta]Konfigurierte Server[/]")
            yield RichLog(id="active-servers", wrap=True)

            yield Static("")
            yield Static("[bold magenta]Verfuegbare Server[/]")
            yield RichLog(id="available-servers", wrap=True)

            yield Static("")
            yield Static("[bold magenta]Custom Server hinzufuegen[/]")
            with Vertical():
                yield Label("Server Name")
                yield Input(placeholder="mein-server", id="new-name")
                yield Label("URL oder Command")
                yield Input(placeholder="http://localhost:8080 oder node script.js", id="new-url")
                yield Button("Hinzufuegen", variant="primary", id="add-btn")

            yield Static("")
            yield RichLog(id="mcp-status", wrap=True)

        yield Footer()

    async def on_mount(self) -> None:
        await self._refresh_servers()

    async def _refresh_servers(self) -> None:
        active_log = self.query_one("#active-servers", RichLog)
        active_log.clear()

        configured = self.config.get("mcp_servers", {})
        if not configured:
            active_log.write("[dim]Keine MCP Server konfiguriert.[/]")
        else:
            for name, cfg in configured.items():
                if isinstance(cfg, dict):
                    is_active = cfg.get("active", False)
                    icon = "[green]●[/]" if is_active else "[red]●[/]"
                    url = cfg.get("url", cfg.get("command", "?"))
                    active_log.write(f"  {icon} [bold]{name}[/]: {url}")
                    if name in KNOWN_MCP_SERVERS:
                        desc = KNOWN_MCP_SERVERS[name].get("description", "")
                        active_log.write(f"      [dim]{desc}[/]")

        avail_log = self.query_one("#available-servers", RichLog)
        avail_log.clear()

        for name, info in KNOWN_MCP_SERVERS.items():
            is_configured = name in configured
            icon = "[green]●[/]" if is_configured else "[dim]○[/]"
            desc = info.get("description", "")
            avail_log.write(f"  {icon} [bold]{name}[/]: {desc}")
            if not is_configured:
                avail_log.write(f"      [dim]Nicht konfiguriert — 'A' zum Hinzufuegen[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            name = self.query_one("#new-name", Input).value.strip()
            url = self.query_one("#new-url", Input).value.strip()
            if not name or not url:
                self.notify("Name und URL/Command sind Pflicht!", severity="error")
                return

            server_config: dict = {"active": True}
            if url.startswith("http"):
                server_config["url"] = url
            else:
                parts = url.split()
                server_config["command"] = parts[0]
                server_config["args"] = parts[1:] if len(parts) > 1 else []

            servers = self.config.get("mcp_servers", {})
            if not isinstance(servers, dict):
                servers = {}
            servers[name] = server_config
            self.config.set("mcp_servers", servers)
            self.config.save()

            self.query_one("#new-name", Input).clear()
            self.query_one("#new-url", Input).clear()

            status = self.query_one("#mcp-status", RichLog)
            status.write(f"[green]Server '{name}' hinzugefuegt![/]")
            self.notify(f"MCP Server '{name}' hinzugefuegt!")

    async def action_add_server(self) -> None:
        """Auto-add all known servers that aren't configured yet."""
        servers = self.config.get("mcp_servers", {})
        if not isinstance(servers, dict):
            servers = {}

        added = 0
        for name, info in KNOWN_MCP_SERVERS.items():
            if name not in servers:
                server_config: dict = {"active": info.get("default_active", False)}
                if "url" in info:
                    server_config["url"] = info["url"]
                if "command" in info:
                    server_config["command"] = info["command"]
                    server_config["args"] = info.get("args", [])
                servers[name] = server_config
                added += 1

        self.config.set("mcp_servers", servers)
        self.config.save()

        status = self.query_one("#mcp-status", RichLog)
        if added > 0:
            status.write(f"[green]{added} Server hinzugefuegt![/]")
            await self._refresh_servers()
        else:
            status.write("[dim]Alle bekannten Server bereits konfiguriert.[/]")

    def action_go_back(self) -> None:
        self.app.pop_screen()
