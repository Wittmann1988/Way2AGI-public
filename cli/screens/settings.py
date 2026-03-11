"""Settings screen — Provider, API-Key, Model, Temperature, MaxTokens, RepeatPenalty."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Footer, Static, Select, Input, Button, Label, Switch,
)
from textual.containers import Vertical, Horizontal, VerticalScroll

from cli.config import Way2AGIConfig

PROVIDERS = [
    ("Anthropic (Claude) ★", "anthropic"),
    ("OpenRouter (586 Models)", "openrouter"),
    ("Groq (Ultra-Fast)", "groq"),
    ("Ollama (Local)", "ollama"),
    ("OpenAI (GPT)", "openai"),
    ("Google (Gemini)", "google"),
    ("Custom (OpenAI-compatible)", "custom"),
]


class SettingsScreen(Screen):
    """Provider, model, and generation settings."""

    BINDINGS = [("escape", "go_back", "Zurueck")]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static("[bold cyan]Settings[/]", classes="screen-title")
        with VerticalScroll(id="settings-form"):
            yield Label("Provider")
            yield Select(
                PROVIDERS,
                value=self.config.provider,
                id="provider-select",
            )
            yield Label("API Key")
            yield Input(
                value=self.config.provider_config.get("api_key", ""),
                password=True,
                placeholder="API Key (leer = Env-Variable)",
                id="api-key-input",
            )
            yield Label("Modell")
            yield Select(
                self._model_options(),
                value=self.config.model,
                id="model-select",
            )

            yield Static("")
            yield Static("[bold magenta]Generation Settings[/]")

            yield Label("Temperature (0.0 - 2.0)")
            yield Input(
                value=str(self.config.temperature),
                placeholder="0.7",
                id="temperature-input",
            )

            yield Label("Max Tokens")
            yield Input(
                value=str(self.config.max_tokens),
                placeholder="4096",
                id="max-tokens-input",
            )

            yield Label("Repeat Penalty (1.0 - 2.0)")
            yield Input(
                value=str(self.config.repeat_penalty),
                placeholder="1.3",
                id="repeat-penalty-input",
            )

            yield Static("")
            yield Static("[bold magenta]Memory[/]")

            yield Label("Memory Server URL")
            yield Input(
                value=self.config.get("memory.server_url", "http://YOUR_CONTROLLER_IP:5555"),
                placeholder="http://YOUR_CONTROLLER_IP:5555",
                id="memory-url-input",
            )

            yield Static("")
            yield Label("Custom Provider (OpenAI-compatible)")
            yield Input(
                value=self.config.get("providers.custom.base_url", ""),
                placeholder="https://api.example.com/v1",
                id="custom-url-input",
            )

            with Horizontal():
                yield Button("Speichern", variant="primary", id="save-btn")
                yield Button("Zurueck", id="back-btn")
        yield Footer()

    def _model_options(self) -> list[tuple[str, str]]:
        models = self.config.provider_config.get("models", [])
        return [(m, m) for m in models] if models else [("(keine)", "")]

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider-select":
            self.config.set("provider", event.value)
            model_select = self.query_one("#model-select", Select)
            new_options = self._model_options()
            model_select.set_options(new_options)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_settings()
        elif event.button.id == "back-btn":
            self.action_go_back()

    def _save_settings(self) -> None:
        api_input = self.query_one("#api-key-input", Input)
        self.config.set(
            f"providers.{self.config.provider}.api_key",
            api_input.value,
        )

        custom_url = self.query_one("#custom-url-input", Input)
        if custom_url.value:
            self.config.set("providers.custom.base_url", custom_url.value)

        model_select = self.query_one("#model-select", Select)
        if model_select.value and model_select.value != Select.BLANK:
            self.config.set("model", str(model_select.value))

        # Generation settings
        try:
            temp = float(self.query_one("#temperature-input", Input).value)
            self.config.set("temperature", max(0.0, min(2.0, temp)))
        except ValueError:
            pass

        try:
            tokens = int(self.query_one("#max-tokens-input", Input).value)
            self.config.set("max_tokens", max(1, min(128000, tokens)))
        except ValueError:
            pass

        try:
            penalty = float(self.query_one("#repeat-penalty-input", Input).value)
            self.config.set("repeat_penalty", max(1.0, min(2.0, penalty)))
        except ValueError:
            pass

        memory_url = self.query_one("#memory-url-input", Input).value
        if memory_url:
            self.config.set("memory.server_url", memory_url)

        self.config.save()
        self.notify("Einstellungen gespeichert!")

    def action_go_back(self) -> None:
        self.app.pop_screen()
