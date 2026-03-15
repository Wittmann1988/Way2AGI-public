"""Status panel showing current provider, memory, model info, and node grid."""
from __future__ import annotations
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult
from rich.text import Text
from cli.config import Way2AGIConfig, NODES


class StatusPanel(Static):
    """Left-side status display."""

    def __init__(self, config: Way2AGIConfig) -> None:
        self.config = config
        super().__init__()
        self.add_class("status-panel")

    def render(self) -> str:
        lines = [
            "[bold cyan]System Status[/]",
            f"  Provider:    [bold]{self.config.provider}[/]",
            f"  Model:       [bold]{self.config.model}[/]",
        ]
        if self.config.get("memory.enabled"):
            lines.append("  Memory:      [bold green]ON[/]")
        else:
            lines.append("  Memory:      [bold red]OFF[/]")
        lines.extend([
            f"  Temperature: {self.config.temperature}",
            f"  Max Tokens:  {self.config.max_tokens}",
            "",
            "[bold magenta]Compute Network[/]",
        ])
        for key, node in NODES.items():
            lines.append(f"  {chr(9679)} {node['name']:<20} {node['ip']}")
        return "\n".join(lines)

    def refresh_status(self) -> None:
        self.refresh()


class NodeStatusGrid(Static):
    """Grid showing all compute nodes with live status."""

    def __init__(self) -> None:
        self._statuses: dict[str, bool] = {}
        super().__init__()

    def render(self) -> str:
        lines = ["[bold cyan]Compute Nodes[/]", ""]
        for key, node in NODES.items():
            status = self._statuses.get(key, None)
            if status is True:
                icon = "[bold green]●[/]"
            elif status is False:
                icon = "[bold red]●[/]"
            else:
                icon = "[dim]○[/]"
            models_list = node.get("models", [])
            models_str = ", ".join(models_list[:3])
            if len(models_list) > 3:
                models_str += f" +{len(models_list) - 3}"
            lines.append(f"  {icon} [bold]{node['name']}[/]")
            lines.append(f"    IP: {node['ip']}  Role: {node['role']}")
            lines.append(f"    Models: {models_str}")
            lines.append("")
        return "\n".join(lines)

    def set_status(self, node_key: str, online: bool) -> None:
        self._statuses[node_key] = online
        self.refresh()
