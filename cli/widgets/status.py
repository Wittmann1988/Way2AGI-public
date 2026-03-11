"""Status panel showing current provider, memory, model info, and node grid."""
from __future__ import annotations
from textual.widgets import Static
from cli.config import Way2AGIConfig, NODES


class StatusPanel(Static):
    """Left-side status display with node grid."""

    def __init__(self, config: Way2AGIConfig) -> None:
        self.config = config
        super().__init__(self._render())
        self.add_class("status-panel")

    def _render(self) -> str:
        lines = [
            "[bold cyan]System Status[/]",
            f"  Provider:    [bold]{self.config.provider}[/]",
            f"  Model:       [bold]{self.config.model}[/]",
            f"  Memory:      [bold green]ON[/]" if self.config.get("memory.enabled") else "  Memory:      [bold red]OFF[/]",
            f"  Temperature: {self.config.temperature}",
            f"  Max Tokens:  {self.config.max_tokens}",
            "",
            "[bold magenta]Compute Network[/]",
        ]
        for key, node in NODES.items():
            icon = "●"
            lines.append(f"  {icon} {node['name']:<20} {node['ip']}")
        return "\n".join(lines)

    def refresh_status(self) -> None:
        self.update(self._render())


class NodeStatusGrid(Static):
    """Grid showing all compute nodes with live status."""

    def __init__(self) -> None:
        super().__init__(self._render_grid())
        self._statuses: dict[str, bool] = {}

    def _render_grid(self) -> str:
        lines = ["[bold cyan]Compute Nodes[/]", ""]
        for key, node in NODES.items():
            status = self._statuses.get(key, None)
            if status is True:
                icon = "[bold green]●[/]"
            elif status is False:
                icon = "[bold red]●[/]"
            else:
                icon = "[dim]○[/]"
            models_str = ", ".join(node.get("models", [])[:3])
            if len(node.get("models", [])) > 3:
                models_str += f" +{len(node['models']) - 3}"
            lines.append(f"  {icon} [bold]{node['name']}[/]")
            lines.append(f"    IP: {node['ip']}  Role: {node['role']}")
            lines.append(f"    Models: {models_str}")
            lines.append("")
        return "\n".join(lines)

    def set_status(self, node_key: str, online: bool) -> None:
        self._statuses[node_key] = online
        self.update(self._render_grid())
