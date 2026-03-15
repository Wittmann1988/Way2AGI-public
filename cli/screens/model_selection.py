"""Model Selection Screen — Choose provider, node, and model."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, Button, ListView, ListItem, Label
from textual.containers import Vertical, Horizontal, VerticalScroll

from cli.config import Way2AGIConfig, NODES, CLOUD_PROVIDERS


class ModelSelectionScreen(Screen):
    """Full model selection with all nodes and cloud providers."""

    BINDINGS = [("escape", "go_back", "Dashboard")]

    def __init__(self, config: Way2AGIConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold cyan]Model Selection[/] — Waehle Provider und Modell",
            classes="screen-title",
        )
        with VerticalScroll(id="model-list"):
            # Claude (recommended)
            yield Static(
                "[bold cyan]★ EMPFOHLEN: Claude (Anthropic)[/]",
                classes="model-group-title",
            )
            with Vertical(classes="model-group recommended"):
                yield Button(
                    "claude-sonnet-4-6 (Best Overall)",
                    id="model-anthropic-claude-sonnet-4-6",
                )
                yield Button(
                    "claude-haiku-4-5 (Fast)",
                    id="model-anthropic-claude-haiku-4-5",
                )

            # Local Models (per node)
            yield Static(
                "[bold magenta]LOCAL MODELS (Compute Network)[/]",
                classes="model-group-title",
            )
            for node_key, node in NODES.items():
                with Vertical(classes="model-group"):
                    yield Static(
                        f"[bold]{node['name']}[/] ({node['ip']}) — {node['role']}"
                    )
                    for model_name in node.get("models", []):
                        btn_id = f"model-local-{node_key}-{model_name}".replace(":", "-").replace(".", "-")
                        yield Button(
                            f"  {model_name}",
                            id=btn_id,
                            classes="model-btn",
                        )

            # Cloud APIs
            yield Static(
                "[bold magenta]CLOUD APIs[/]",
                classes="model-group-title",
            )
            for prov_key, prov in CLOUD_PROVIDERS.items():
                if prov_key == "anthropic":
                    continue  # already shown above
                with Vertical(classes="model-group"):
                    yield Static(f"[bold]{prov['name']}[/]")
                    for model_name in prov.get("models", []):
                        btn_id = f"model-{prov_key}-{model_name}".replace("/", "-").replace(":", "-").replace(".", "-")
                        yield Button(
                            f"  {model_name}",
                            id=btn_id,
                            classes="model-btn",
                        )

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if not btn_id.startswith("model-"):
            return

        parts = btn_id.split("-", 2)
        if len(parts) < 3:
            return

        category = parts[1]
        model_label = event.button.label.plain.strip()

        if category == "anthropic":
            self.config.set("provider", "anthropic")
            self.config.set("model", model_label.split(" (")[0])
        elif category == "local":
            # local-{node_key}-{model}
            rest = btn_id[len("model-local-"):]
            node_key = rest.split("-", 1)[0]
            node = NODES.get(node_key, {})
            ollama_port = node.get("ollama_port", 11434)
            ip = node.get("ip", "YOUR_INFERENCE_NODE_IP")
            self.config.set("provider", "ollama")
            self.config.set("providers.ollama.base_url", f"http://{ip}:{ollama_port}/v1")
            self.config.set("model", model_label)
        else:
            # cloud provider
            prov = CLOUD_PROVIDERS.get(category, {})
            if prov:
                self.config.set("provider", category)
                self.config.set(f"providers.{category}.base_url", prov["base_url"])
                self.config.set("model", model_label)

        self.config.save()
        self.notify(f"Modell: {model_label} ({category})")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
