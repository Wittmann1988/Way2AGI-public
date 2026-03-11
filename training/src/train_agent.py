"""
Agent-spezifisches SFT Training auf Desktop WSL2 (YOUR_GPU).

Trainiert einzelne Agents (orchestrator, memory, consciousness) auf ihren
spezialisierten Traces, bevor die Faehigkeiten ins Haupt-Elias-Modell fliessen.

Usage:
  python -m training.src.train_agent --agent way2agi-orchestrator --data traces.jsonl
  python -m training.src.train_agent --agent way2agi-memory-agent --data traces.jsonl --epochs 5
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Agent-spezifische Konfigurationen
AGENT_CONFIGS = {
    "way2agi-orchestrator": {
        "base_model": "Qwen/Qwen3-1.7B",
        "description": "Task-Zerlegung, Model-Routing, Pipeline-Management",
        "lora_r": 16,
        "lora_alpha": 32,
        "max_length": 2048,
    },
    "way2agi-memory-agent": {
        "base_model": "Qwen/Qwen3-1.7B",
        "description": "Memory Storage, Retrieval, Knowledge Graph",
        "lora_r": 16,
        "lora_alpha": 32,
        "max_length": 1024,
    },
    "way2agi-consciousness": {
        "base_model": "Qwen/Qwen3-1.7B",
        "description": "Self-Mirroring, Identity, Reflexion",
        "lora_r": 16,
        "lora_alpha": 32,
        "max_length": 2048,
    },
}

# Default-Werte
DEFAULT_EPOCHS = 3
DEFAULT_LR = 2e-4
DEFAULT_BATCH_SIZE = 2
DEFAULT_GRADIENT_ACCUM = 8


def setup_logging(agent_name: str) -> None:
    artifacts = Path(os.environ.get("WAY2AGI_ARTIFACTS", "./training/artifacts"))
    artifacts.mkdir(parents=True, exist_ok=True)
    log_file = artifacts / f"{agent_name}-training.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_training_data(data_path: str) -> list[dict]:
    """Lade JSONL Trainingsdaten."""
    data = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    logger.info("Loaded %d training examples from %s", len(data), data_path)
    return data


def train(agent_name: str, data_path: str, epochs: int, lr: float) -> None:
    """Fuehrt SFT-Training fuer einen spezifischen Agent durch."""

    config = AGENT_CONFIGS.get(agent_name)
    if not config:
        logger.error("Unknown agent: %s. Available: %s", agent_name, list(AGENT_CONFIGS.keys()))
        sys.exit(1)

    # Imports hier um schnelles --help zu ermoeglichen
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer, SFTConfig
    except ImportError as e:
        logger.error("Missing dependency: %s. Run: pip install torch transformers peft trl datasets", e)
        sys.exit(1)

    # GPU check
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info("GPU: %s (%.1f GB VRAM)", gpu_name, gpu_mem)
    else:
        logger.warning("KEINE GPU verfuegbar! Training wird sehr langsam.")

    # Trainingsdaten laden
    raw_data = load_training_data(data_path)
    if len(raw_data) < 5:
        logger.error("Zu wenig Trainingsdaten (%d). Minimum: 5.", len(raw_data))
        sys.exit(1)

    dataset = Dataset.from_list(raw_data)

    # Train/Eval Split
    if len(dataset) > 20:
        split = dataset.train_test_split(test_size=0.1, seed=42)
        train_dataset = split["train"]
        eval_dataset = split["test"]
    else:
        train_dataset = dataset
        eval_dataset = None

    logger.info(
        "Dataset: %d train, %d eval",
        len(train_dataset),
        len(eval_dataset) if eval_dataset else 0,
    )

    # Output dir
    project_root = Path(os.environ.get("WAY2AGI_ROOT", "."))
    output_dir = project_root / "training" / "artifacts" / agent_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Model + Tokenizer
    logger.info("Loading base model: %s", config["base_model"])
    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    # LoRA Config
    lora_config = LoraConfig(
        r=config["lora_r"],
        lora_alpha=config["lora_alpha"],
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )

    # SFT Config
    training_args = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=DEFAULT_BATCH_SIZE,
        gradient_accumulation_steps=DEFAULT_GRADIENT_ACCUM,
        learning_rate=lr,
        max_length=config["max_length"],
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset else "no",
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        report_to="none",
        save_total_limit=2,
    )

    # Trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    # Training!
    logger.info("=== Starting SFT for %s ===", agent_name)
    logger.info("  Base model: %s", config["base_model"])
    logger.info("  LoRA: r=%d, alpha=%d", config["lora_r"], config["lora_alpha"])
    logger.info("  Epochs: %d, LR: %s, Batch: %d x %d", epochs, lr, DEFAULT_BATCH_SIZE, DEFAULT_GRADIENT_ACCUM)

    t0 = time.time()
    result = trainer.train()
    duration = time.time() - t0

    logger.info("=== Training complete in %.1f min ===", duration / 60)
    logger.info("  Loss: %.4f", result.training_loss)

    # Save
    trainer.save_model(str(output_dir / "final"))
    tokenizer.save_pretrained(str(output_dir / "final"))
    logger.info("Model saved to %s/final", output_dir)

    # Summary
    summary = {
        "agent": agent_name,
        "base_model": config["base_model"],
        "training_examples": len(train_dataset),
        "epochs": epochs,
        "final_loss": result.training_loss,
        "duration_min": round(duration / 60, 1),
        "output_dir": str(output_dir / "final"),
    }
    summary_path = output_dir / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Summary: %s", json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description="Way2AGI Agent SFT Training")
    parser.add_argument("--agent", required=True, help="Agent name (way2agi-orchestrator, way2agi-memory-agent, way2agi-consciousness)")
    parser.add_argument("--data", required=True, help="Path to JSONL training data")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    args = parser.parse_args()

    setup_logging(args.agent)
    train(args.agent, args.data, args.epochs, args.lr)


if __name__ == "__main__":
    main()
