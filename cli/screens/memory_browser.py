"""Memory Browser — Search memories, browse entities, view knowledge graph."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, Input, DataTable, RichLog
from textual.containers import Vertical, Horizontal

from cli.config import Way2AGIConfig


class MemoryBrowserScreen(Screen):
    """Browse and search stored memories, entities, and relations."""

    BINDINGS = [
        ("escape", "go_back", "Dashboard"),
        ("f2", "show_entities", "Entities"),
        ("f3", "show_relations", "Relations"),
    ]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static("[bold cyan]Memory Browser[/] — [dim]F2: Entities  F3: Relations[/]", classes="screen-title")
        yield Input(placeholder="Suche in Erinnerungen...", id="memory-search")
        yield DataTable(id="memory-table")
        yield RichLog(id="entity-log", wrap=True)
        yield Static("", id="memory-stats")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.add_columns("Typ", "Inhalt", "Wichtigkeit", "Erstellt")

        entity_log = self.query_one("#entity-log", RichLog)
        entity_log.display = False

        await self._load_stats()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        await self._search(query)

    async def _search(self, query: str) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.clear()
        table.display = True
        self.query_one("#entity-log", RichLog).display = False

        server_url = self.config.get("memory.server_url", "http://YOUR_INFERENCE_NODE_IP:5555")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{server_url}/memory/query",
                    json={"query": query, "top_k": 20, "memory_type": "all"},
                )
                if resp.status_code == 200:
                    results = resp.json()
                    if isinstance(results, list):
                        for r in results:
                            if isinstance(r, dict):
                                table.add_row(
                                    r.get("type", "?"),
                                    r.get("content", "")[:80],
                                    f"{r.get('importance', 0):.2f}",
                                    r.get("created_at", "")[:10],
                                )
                    stats = self.query_one("#memory-stats", Static)
                    count = len(results) if isinstance(results, list) else 0
                    stats.update(f"{count} Ergebnis(se) gefunden")
                else:
                    stats = self.query_one("#memory-stats", Static)
                    stats.update(f"Server Error: HTTP {resp.status_code}")
        except Exception as e:
            stats = self.query_one("#memory-stats", Static)
            stats.update(f"Memory Server nicht erreichbar: {e}")

    async def action_show_entities(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.display = False
        entity_log = self.query_one("#entity-log", RichLog)
        entity_log.display = True
        entity_log.clear()

        server_url = self.config.get("memory.server_url", "http://YOUR_INFERENCE_NODE_IP:5555")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{server_url}/entities")
                if resp.status_code == 200:
                    entities = resp.json()
                    entity_log.write("[bold cyan]Knowledge Graph — Entities[/]\n")
                    if isinstance(entities, list):
                        for e in entities:
                            if isinstance(e, dict):
                                name = e.get("name", "?")
                                etype = e.get("type", "?")
                                entity_log.write(f"  [bold magenta]{name}[/] ({etype})")
                            else:
                                entity_log.write(f"  {e}")
                    else:
                        entity_log.write(str(entities))
                else:
                    entity_log.write(f"[red]HTTP {resp.status_code}[/]")
        except Exception as e:
            entity_log.write(f"[red]Nicht erreichbar: {e}[/]")

    async def action_show_relations(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.display = False
        entity_log = self.query_one("#entity-log", RichLog)
        entity_log.display = True
        entity_log.clear()

        server_url = self.config.get("memory.server_url", "http://YOUR_INFERENCE_NODE_IP:5555")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{server_url}/relations")
                if resp.status_code == 200:
                    relations = resp.json()
                    entity_log.write("[bold cyan]Knowledge Graph — Relations[/]\n")
                    if isinstance(relations, list):
                        for r in relations:
                            if isinstance(r, dict):
                                src = r.get("source", "?")
                                rel = r.get("relation", "?")
                                tgt = r.get("target", "?")
                                entity_log.write(f"  [cyan]{src}[/] —[magenta]{rel}[/]→ [cyan]{tgt}[/]")
                            else:
                                entity_log.write(f"  {r}")
                    else:
                        entity_log.write(str(relations))
                else:
                    entity_log.write(f"[red]HTTP {resp.status_code}[/]")
        except Exception as e:
            entity_log.write(f"[red]Nicht erreichbar: {e}[/]")

    async def _load_stats(self) -> None:
        stats = self.query_one("#memory-stats", Static)
        server_url = self.config.get("memory.server_url", "http://YOUR_INFERENCE_NODE_IP:5555")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{server_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    total = data.get("total_memories", data.get("memories", "?"))
                    entities = data.get("total_entities", data.get("entities", "?"))
                    stats.update(
                        f"Memories: {total} | Entities: {entities} | "
                        f"Server: {server_url}"
                    )
                    return
        except Exception:
            pass
        stats.update(f"Memory Server nicht erreichbar ({server_url})")

    def action_go_back(self) -> None:
        self.app.pop_screen()
