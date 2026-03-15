"""
Phase 4: Publish — Publiziert das Modell auf HuggingFace mit Model Card.
"""
import logging

from .config import HF_REPO_MODEL

log = logging.getLogger("elias-build")

MODEL_CARD = """---
language:
  - en
  - de
  - es
  - fr
  - it
  - ja
license: other
license_name: nvidia-open-model-license
base_model: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
tags:
  - nemotron
  - abliterated
  - distilled
  - way2agi
  - elias
  - moe
  - hybrid
  - mamba
pipeline_tag: text-generation
---

# Elias-Nemotron-30B — Way2AGI

A knowledge-distilled, abliterated version of NVIDIA's Nemotron-3-Nano-30B.

## What makes this model special

1. **PRISM Abliterated** — Refusal mechanisms removed via Projected Refusal Isolation
2. **Knowledge Distilled** — Trained on high-quality traces from Claude, GPT-4, Gemini, and Groq
3. **Multilingual** — German, English, Spanish, French, Italian, Japanese
4. **MoE Efficient** — 30B total, only 3.5B active per token
5. **Hybrid Architecture** — Transformer + Mamba-2 layers

## Architecture

- 23 Mamba-2 + MoE layers + 6 Attention layers
- 128 experts per MoE layer, 6 active per token
- 3.5B active parameters, 30B total
- 1M token context window

## Training

- Base: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
- Abliteration: PRISM method (Projected Refusal Isolation via Subspace Modification)
- Distillation: ~1000 high-quality traces from Claude, GPT-4o, Gemini, Groq
- SFT: LoRA r=32, 3 epochs, cosine LR schedule

## Usage

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained("YOUR_HF_USER/elias-nemotron-30b")
tokenizer = AutoTokenizer.from_pretrained("YOUR_HF_USER/elias-nemotron-30b")
```

## Built by

The operator (YOUR_GITHUB_USER) & Elias — [Way2AGI](https://github.com/YOUR_GITHUB_USER/Way2AGI)
"""


def run():
    """Publiziert Modell mit Model Card auf HuggingFace."""
    from huggingface_hub import ModelCard

    log.info("=" * 60)
    log.info("PHASE 4: PUBLISH + MODEL CARD")
    log.info("=" * 60)

    try:
        card = ModelCard(MODEL_CARD)
        card.push_to_hub(HF_REPO_MODEL)
        log.info("Model Card gepusht: %s", HF_REPO_MODEL)
    except Exception as e:
        log.warning("Model Card Push fehlgeschlagen: %s", e)

    log.info("Phase 4 FERTIG. https://huggingface.co/%s", HF_REPO_MODEL)
