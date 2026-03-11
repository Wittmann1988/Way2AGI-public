"""Way2AGI Textual Application — Cyberpunk TUI for Cognitive AI Agent."""
from textual.app import App
from textual.theme import Theme
from cli.config import Way2AGIConfig
from cli.bootstrap import ensure_data_dir, is_first_run, run_first_time_setup


class Way2AGIApp(App):
    """Way2AGI Terminal Application — Cyberpunk Edition."""

    TITLE = "Way2AGI"
    SUB_TITLE = "Cognitive AI Agent"
    CSS_PATH = "app.tcss"

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, start_screen: str = "dashboard"):
        super().__init__()
        self._start_screen = start_screen
        self.config = Way2AGIConfig()

    def on_mount(self) -> None:
        from cli.screens.dashboard import DashboardScreen
        from cli.screens.chat import ChatScreen
        from cli.screens.settings import SettingsScreen
        from cli.screens.memory_browser import MemoryBrowserScreen
        from cli.screens.diagnostics import DiagnosticsScreen
        from cli.screens.model_selection import ModelSelectionScreen
        from cli.screens.orchestrator import OrchestratorScreen
        from cli.screens.sysmon import SystemMonitorScreen
        from cli.screens.mcp_manager import MCPManagerScreen

        self.install_screen(DashboardScreen(self.config), name="dashboard")
        self.install_screen(ChatScreen(self.config), name="chat")
        self.install_screen(SettingsScreen(self.config), name="settings")
        self.install_screen(MemoryBrowserScreen(self.config), name="memory")
        self.install_screen(DiagnosticsScreen(self.config), name="diagnostics")
        self.install_screen(ModelSelectionScreen(self.config), name="models")
        self.install_screen(OrchestratorScreen(self.config), name="orchestrator")
        self.install_screen(SystemMonitorScreen(self.config), name="sysmon")
        self.install_screen(MCPManagerScreen(self.config), name="mcp")

        ensure_data_dir()
        if is_first_run():
            run_first_time_setup(self.config)

        self.push_screen(self._start_screen)
