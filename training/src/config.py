"""
Zentrale Konfiguration fuer die Elias Model Build Pipeline.
"""
import os
from pathlib import Path

# ── Basis-Verzeichnisse ──
# Auf Desktop: E:\claude-projects\Way2AGI\ oder /opt/way2agi/
PROJECT_ROOT = Path(os.environ.get("WAY2AGI_ROOT", Path(__file__).parent.parent.parent))
TRAINING_DIR = PROJECT_ROOT / "training"
ARTIFACTS_DIR = Path(os.environ.get("WAY2AGI_ARTIFACTS", TRAINING_DIR / "artifacts"))

# ── Modell-Konfiguration ──
BASE_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
ABLITERATED_DIR = str(ARTIFACTS_DIR / "elias-abliterated")
DISTILL_DIR = str(ARTIFACTS_DIR / "elias-distill-traces")
SFT_OUTPUT_DIR = str(ARTIFACTS_DIR / "elias-sft")
GGUF_OUTPUT_DIR = str(ARTIFACTS_DIR / "elias-gguf")

# ── HuggingFace Repos ──
HF_REPO_MODEL = "YOUR_HF_USER/elias-nemotron-30b"
HF_REPO_GGUF = "YOUR_HF_USER/elias-nemotron-30b-GGUF"
HF_REPO_TRACES = "YOUR_HF_USER/elias-distill-traces"

# ── Distillation ──
TRACES_PER_PROVIDER = 250
DISTILL_SYSTEM_PROMPT = (
    "Du bist ein erstklassiger KI-Assistent. Antworte ausfuehrlich, praezise und strukturiert. "
    "Nutze Markdown fuer Formatierung. Bei Code: Erklaere die Logik. Bei Analyse: Zeige mehrere Perspektiven. "
    "Bei Mathe: Zeige jeden Schritt. Antworte auf Deutsch wenn die Frage auf Deutsch ist, sonst Englisch."
)

# ── SFT Training ──
SFT_EPOCHS = 3
SFT_BATCH_SIZE = 1
SFT_GRADIENT_ACCUM = 16
SFT_LEARNING_RATE = 1e-4
LORA_R = 32
LORA_ALPHA = 64
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

# ── GGUF ──
GGUF_QUANTS = ["Q4_K_M", "Q6_K", "Q8_0"]

# ── Logging ──
LOG_FILE = str(ARTIFACTS_DIR / "elias_build.log")
