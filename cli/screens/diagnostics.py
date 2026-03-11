"""Diagnostics screen — Comprehensive system health checks across all nodes."""
from __future__ import annotations

import os
import shutil
import sys
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, RichLog, Button

from cli.config import Way2AGIConfig, NODES, CLOUD_PROVIDERS


class DiagnosticsScreen(Screen):
    """Run comprehensive system diagnostics across all nodes."""

    BINDINGS = [("escape", "go_back", "Dashboard")]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static("[bold cyan]Way2AGI Diagnostics[/]", classes="screen-title")
        yield RichLog(id="diag-log", wrap=True)
        yield Button("Erneut pruefen", id="rerun-btn")
        yield Footer()

    async def on_mount(self) -> None:
        await self._run_checks()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rerun-btn":
            log = self.query_one("#diag-log", RichLog)
            log.clear()
            await self._run_checks()

    async def _run_checks(self) -> None:
        log = self.query_one("#diag-log", RichLog)
        errors = 0
        warnings = 0

        log.write("[bold cyan]═══ System Checks ═══[/]\n")

        # Python
        v = sys.version.split()[0]
        major = int(v.split(".")[0])
        minor = int(v.split(".")[1])
        ok = major >= 3 and minor >= 11
        log.write(f"{'[green][OK][/]' if ok else '[red][FAIL][/]'}   Python: {v}")
        if not ok:
            errors += 1

        # Config
        if self.config.path.exists():
            log.write(f"[green][OK][/]   Config: {self.config.path}")
        else:
            log.write("[yellow][WARN][/] Config: nicht gefunden — wird beim Speichern erstellt")
            warnings += 1

        # Required packages
        for pkg in ["textual", "httpx", "click", "rich"]:
            try:
                __import__(pkg)
                log.write(f"[green][OK][/]   Package: {pkg}")
            except ImportError:
                log.write(f"[red][FAIL][/] Package: {pkg} nicht installiert")
                errors += 1

        # Node.js (optional)
        node = shutil.which("node")
        if node:
            log.write(f"[green][OK][/]   Node.js: {node}")
        else:
            log.write("[dim][INFO][/] Node.js: nicht gefunden (optional)")

        log.write("")
        log.write("[bold cyan]═══ Compute Network ═══[/]\n")

        # Check all nodes
        for key, node_cfg in NODES.items():
            ip = node_cfg["ip"]
            name = node_cfg["name"]

            # Ollama check
            ollama_port = node_cfg.get("ollama_port")
            if ollama_port:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(f"http://{ip}:{ollama_port}/api/tags")
                        if resp.status_code == 200:
                            models = resp.json().get("models", [])
                            log.write(f"[green][OK][/]   {name} Ollama: {len(models)} models")
                        else:
                            log.write(f"[yellow][WARN][/] {name} Ollama: HTTP {resp.status_code}")
                            warnings += 1
                except Exception:
                    log.write(f"[red][FAIL][/] {name} Ollama ({ip}:{ollama_port}): nicht erreichbar")
                    errors += 1

            # Daemon check
            daemon_port = node_cfg.get("port")
            if daemon_port:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(f"http://{ip}:{daemon_port}/health")
                        if resp.status_code == 200:
                            log.write(f"[green][OK][/]   {name} Daemon: online (:{daemon_port})")
                        else:
                            log.write(f"[yellow][WARN][/] {name} Daemon: HTTP {resp.status_code}")
                            warnings += 1
                except Exception:
                    log.write(f"[yellow][WARN][/] {name} Daemon ({ip}:{daemon_port}): offline")
                    warnings += 1

        log.write("")
        log.write("[bold cyan]═══ Memory Server ═══[/]\n")

        # Memory Server
        server_url = self.config.get("memory.server_url", "http://YOUR_CONTROLLER_IP:5555")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{server_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    total = data.get("total_memories", data.get("memories", "?"))
                    log.write(f"[green][OK][/]   Memory Server: {total} memories ({server_url})")
                else:
                    log.write(f"[red][FAIL][/] Memory Server: HTTP {resp.status_code}")
                    errors += 1
        except Exception:
            log.write(f"[yellow][WARN][/] Memory Server: nicht erreichbar ({server_url})")
            warnings += 1

        log.write("")
        log.write("[bold cyan]═══ API Keys ═══[/]\n")

        # Provider keys
        for prov_key, prov_cfg in CLOUD_PROVIDERS.items():
            env_key = prov_cfg.get("env_key", "")
            config_key = self.config.get(f"providers.{prov_key}.api_key", "")
            env_val = os.environ.get(env_key, "")
            has_key = bool(config_key) or bool(env_val)
            if has_key:
                log.write(f"[green][OK][/]   {prov_cfg['name']}: Key vorhanden")
            else:
                log.write(f"[yellow][WARN][/] {prov_cfg['name']}: Kein Key ({env_key})")
                warnings += 1

        log.write("")
        log.write("[bold cyan]═══ MCP Servers ═══[/]\n")

        mcp_servers = self.config.get("mcp_servers", {})
        if isinstance(mcp_servers, dict):
            for name, cfg in mcp_servers.items():
                if isinstance(cfg, dict):
                    active = cfg.get("active", False)
                    icon = "[green][OK][/]" if active else "[dim][OFF][/]"
                    log.write(f"{icon}   MCP: {name}")
        else:
            log.write("[dim][INFO][/] Keine MCP Server konfiguriert")

        log.write("")
        log.write("[bold cyan]═══ Skills ═══[/]\n")

        skills = self.config.get("skills", {})
        if isinstance(skills, dict):
            for skill_name, enabled in skills.items():
                icon = "[green][OK][/]" if enabled else "[dim][OFF][/]"
                log.write(f"{icon}   Skill: {skill_name}")

        # Summary
        log.write("")
        log.write("[bold cyan]═══════════════════════[/]")
        if errors == 0 and warnings == 0:
            log.write("[bold green]Alle Checks bestanden![/]")
        elif errors == 0:
            log.write(f"[bold yellow]{warnings} Warnung(en), keine kritischen Fehler.[/]")
        else:
            log.write(f"[bold red]{errors} Fehler, {warnings} Warnungen.[/]")

    def action_go_back(self) -> None:
        self.app.pop_screen()
