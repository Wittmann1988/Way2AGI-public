"""Way2AGI Configuration Manager."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path.home() / ".way2agi"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

# Compute Network Nodes
NODES = {
    "jetson": {
        "name": "YOUR_CONTROLLER_DEVICE",
        "ip": "YOUR_CONTROLLER_IP",
        "ssh": "YOUR_CONTROLLER_USER@YOUR_CONTROLLER_IP",
        "ssh_pass": "jetson",
        "port": 8050,
        "ollama_port": 11434,
        "llama_port": 8080,
        "memory_port": 5555,
        "role": "Controller, Memory, Always-On",
        "ram": "64GB",
        "models": [
            "lfm2:24b", "nemotron-3-nano:30b", "smallthinker:1.8b",
            "way2agi-orchestrator-qwen3:8b", "way2agi-memory-qwen3:8b",
            "way2agi-consciousness-qwen3:8b", "olmo-3:7b", "olmo-3:7b-think",
            "olmo-3:32b-think", "qwen3:1.7b", "qwen3:4b", "qwen3:8b",
            "qwen3-abliterated:8b", "llama3.2:3b",
        ],
    },
    "desktop": {
        "name": "Desktop YOUR_GPU",
        "ip": "YOUR_DESKTOP_IP",
        "ssh": "YOUR_SSH_USER@YOUR_DESKTOP_IP",
        "port": 8100,
        "ollama_port": 11434,
        "role": "Heavy Compute, Training",
        "gpu": "YOUR_GPU 32GB",
        "models": [
            "lfm2:24b", "step-3.5-flash", "qwen3.5:9b",
        ],
    },
    "zenbook": {
        "name": "Zenbook Laptop",
        "ip": "YOUR_LAPTOP_IP",
        "ssh": "erik@YOUR_LAPTOP_IP",
        "port": 8150,
        "role": "NPU Node, Orchestration",
        "models": [
            "lfm2:24b", "smallthinker:1.8b", "qwen3:1.7b",
        ],
    },
    "s24": {
        "name": "S24 Tablet",
        "ip": "YOUR_MOBILE_IP",
        "ssh_port": 8022,
        "ssh": "u0_a401@YOUR_MOBILE_IP",
        "port": 8200,
        "ollama_port": 11434,
        "role": "Light Node, Verification",
        "models": ["qwen3:1.7b"],
    },
    "s25": {
        "name": "S25 Ultra",
        "ip": "YOUR_PHONE_IP",
        "ssh_port": 8022,
        "ssh": "u0_a401@YOUR_PHONE_IP",
        "port": 8200,
        "role": "Light Node",
        "models": ["qwen3-abliterated:8b"],
    },
}

# Cloud API providers
CLOUD_PROVIDERS = {
    "groq": {
        "name": "Groq (Ultra-Fast)",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "models": ["moonshotai/kimi-k2", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    },
    "openrouter": {
        "name": "OpenRouter (586 Models)",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "models": ["qwen/qwen3-coder", "stepfun/step-2-16k-exp", "google/gemini-2.5-flash-preview"],
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    },
    "google": {
        "name": "Google (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
    },
}

# Jetson Daemon API endpoints
DAEMON_ENDPOINTS = {
    "health": "http://YOUR_CONTROLLER_IP:8050/health",
    "nodes": "http://YOUR_CONTROLLER_IP:8050/nodes",
    "job": "http://YOUR_CONTROLLER_IP:8050/job",
    "roundtable": "http://YOUR_CONTROLLER_IP:8050/roundtable",
}

MEMORY_INJECT_URL = "http://YOUR_CONTROLLER_IP:5555/memory/inject"
MEMORY_QUERY_URL = "http://YOUR_CONTROLLER_IP:5555/memory/query"
MEMORY_HEALTH_URL = "http://YOUR_CONTROLLER_IP:5555/health"


class Way2AGIConfig:
    """Manages ~/.way2agi/config.json."""

    def __init__(self, config_path: Path | None = None):
        self.path = config_path or DEFAULT_CONFIG_PATH
        self._data: dict[str, Any] = self._defaults()
        if self.path.exists():
            with open(self.path) as f:
                saved = json.load(f)
            self._data = _deep_merge(self._defaults(), saved)

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "version": "2.0.0",
            "user_name": "the user",
            "language": "de",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "temperature": 0.7,
            "max_tokens": 4096,
            "repeat_penalty": 1.3,
            "providers": {
                "openrouter": {
                    "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
                    "base_url": "https://openrouter.ai/api/v1",
                    "models": ["qwen/qwen3-coder", "stepfun/step-2-16k-exp"],
                },
                "groq": {
                    "api_key": os.environ.get("GROQ_API_KEY", ""),
                    "base_url": "https://api.groq.com/openai/v1",
                    "models": ["moonshotai/kimi-k2", "llama-3.3-70b-versatile"],
                },
                "ollama": {
                    "api_key": "",
                    "base_url": "http://YOUR_CONTROLLER_IP:11434/v1",
                    "models": [],
                },
                "anthropic": {
                    "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                    "base_url": "https://api.anthropic.com/v1",
                    "models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
                },
                "openai": {
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                    "base_url": "https://api.openai.com/v1",
                    "models": ["gpt-4o", "gpt-4o-mini"],
                },
                "google": {
                    "api_key": os.environ.get("GEMINI_API_KEY", ""),
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
                },
                "custom": {
                    "api_key": "",
                    "base_url": "",
                    "models": [],
                },
            },
            "memory": {
                "enabled": True,
                "server_url": "http://YOUR_CONTROLLER_IP:5555",
                "auto_store": True,
                "auto_recall": True,
                "recall_top_k": 3,
            },
            "mcp_servers": {
                "sequential-thinking": {
                    "command": "node",
                    "args": ["~/downloads/mcp-sequential-thinking/dist/index.js"],
                    "active": True,
                },
                "memory": {
                    "url": "http://YOUR_CONTROLLER_IP:5555",
                    "active": True,
                },
            },
            "skills": {
                "file_read": True,
                "file_write": True,
                "shell": True,
                "web_fetch": True,
                "memory_query": True,
                "python_eval": True,
                "roundtable": True,
                "training": True,
                "research": True,
            },
            "autonomy_level": "balanced",
            "drive_weights": {
                "curiosity": 0.7,
                "competence": 0.5,
                "social": 0.4,
                "autonomy": 0.3,
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        d = self._data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        d = self._data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def provider(self) -> str:
        return self._data["provider"]

    @property
    def model(self) -> str:
        return self._data["model"]

    @property
    def temperature(self) -> float:
        return self._data.get("temperature", 0.7)

    @property
    def max_tokens(self) -> int:
        return self._data.get("max_tokens", 4096)

    @property
    def repeat_penalty(self) -> float:
        return self._data.get("repeat_penalty", 1.3)

    @property
    def provider_config(self) -> dict[str, Any]:
        return self._data["providers"].get(self.provider, {})

    @property
    def is_first_run(self) -> bool:
        return not self.path.exists()


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
