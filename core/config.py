# core/config.py
from pydantic_settings import BaseSettings
from pathlib import Path
import os
from typing import Optional


class Way2AGIConfig(BaseSettings):
    # === USER-SPEZIFISCH (nie committen!) ===
    USER_MODEL_PREFIX: str = "myagi"
    HF_USERNAME: str = "your-hf-username"
    PROJECT_ROOT: Path = Path.home() / ".way2agi"

    # === Compute Network (Auto-Discovery) ===
    CONTROLLER_IP: Optional[str] = None
    DESKTOP_IP: Optional[str] = None
    LAPTOP_IP: Optional[str] = None
    MOBILE_IP: Optional[str] = None

    # === API Keys ===
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    HF_TOKEN: str = ""

    # === Resource Budget ===
    MAX_GPU_HOURS_PER_DAY: float = 8.0
    NIGHT_MODE_START: int = 2
    NIGHT_MODE_END: int = 6
    MAX_MODEL_STORAGE_GB: int = 10
    PAUSE_ALL_ON_LOW_POWER: bool = True

    # === Consciousness & Self-Observation ===
    ENABLE_CONSCIOUSNESS: bool = True
    ENABLE_SELF_OBSERVATION: bool = True
    REFLECTION_INTERVAL_MINUTES: int = 10

    # === Hardware Auto-Detection ===
    @property
    def gpu_info(self):
        try:
            import subprocess
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                timeout=5,
            )
            return out.decode().strip()
        except Exception:
            return "CPU-only"

    class Config:
        env_file = "user/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global instance — import everywhere!
config = Way2AGIConfig()
