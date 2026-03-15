"""Way2AGI Cyberpunk Banner widget."""
from textual.widgets import Static

BANNER = r"""[bold cyan] ╦ ╦┌─┐┬ ┬┌─┐[bold magenta]╔═╗╔═╗╦[/]
[bold cyan] ║║║├─┤└┬┘┌─┘[bold magenta]╠═╣║ ╦║[/]
[bold cyan] ╚╩╝┴ ┴ ┴ └─┘[bold magenta]╩ ╩╚═╝╩[/]
[dim cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]
[bold white]  Cognitive AI Agent · Self-Improving · Multi-Node[/]
[dim]  Memory · Orchestration · Training · Research[/]"""


class Way2AGIHeader(Static):
    """Cyberpunk banner displayed at top of dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self.add_class("way2agi-header")

    def render(self) -> str:
        return BANNER
