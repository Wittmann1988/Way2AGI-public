"""
Phase 3: SFT Training — Trainiert abliteriertes Modell mit distillierten Traces.
Nutzt LoRA fuer VRAM-Effizienz auf YOUR_GPU (32GB).
"""
import logging
import sys
from pathlib import Path

from .config import (
    ABLITERATED_DIR, BASE_MODEL, DISTILL_DIR, HF_REPO_MODEL,
    LORA_ALPHA, LORA_DROPOUT, LORA_R, LORA_TARGET_MODULES,
    SFT_BATCH_SIZE, SFT_EPOCHS, SFT_GRADIENT_ACCUM,
    SFT_LEARNING_RATE, SFT_OUTPUT_DIR,
)

log = logging.getLogger("elias-build")


def run():
    """Fuehrt SFT Training aus."""
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from trl import SFTTrainer, SFTConfig

    log.info("=" * 60)
    log.info("PHASE 3: SFT TRAINING")
    log.info("=" * 60)

    trace_file = Path(DISTILL_DIR) / "distill_traces.jsonl"
    if not trace_file.exists():
        log.error("Keine Traces gefunden in %s — Phase 2 zuerst!", trace_file)
        sys.exit(1)

    log.info("Lade Traces aus %s", trace_file)
    dataset = load_dataset("json", data_files=str(trace_file), split="train")
    log.info("Traces geladen: %d Beispiele", len(dataset))

    ds = dataset.train_test_split(test_size=0.05, seed=42)
    log.info("Train: %d, Eval: %d", len(ds["train"]), len(ds["test"]))

    model_path = ABLITERATED_DIR if Path(ABLITERATED_DIR).exists() else BASE_MODEL
    log.info("Trainiere auf Basis: %s", model_path)

    config = SFTConfig(
        output_dir=SFT_OUTPUT_DIR,
        push_to_hub=True,
        hub_model_id=HF_REPO_MODEL,
        hub_strategy="every_save",
        num_train_epochs=SFT_EPOCHS,
        per_device_train_batch_size=SFT_BATCH_SIZE,
        gradient_accumulation_steps=SFT_GRADIENT_ACCUM,
        learning_rate=SFT_LEARNING_RATE,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="steps",
        save_steps=200,
        save_total_limit=3,
        eval_strategy="steps",
        eval_steps=200,
        bf16=True,
        gradient_checkpointing=True,
        max_length=2048,
        report_to="none",
    )

    peft_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=LORA_TARGET_MODULES,
    )

    log.info("SFT: %d Epochen, LoRA r=%d alpha=%d, LR=%s", SFT_EPOCHS, LORA_R, LORA_ALPHA, SFT_LEARNING_RATE)

    trainer = SFTTrainer(
        model=model_path,
        train_dataset=ds["train"],
        eval_dataset=ds["test"],
        peft_config=peft_config,
        args=config,
        model_init_kwargs={
            "torch_dtype": torch.bfloat16,
            "device_map": "auto",
            "trust_remote_code": True,
        },
    )

    train_result = trainer.train()
    log.info("Training abgeschlossen: %s", train_result.metrics)

    trainer.save_model()
    trainer.push_to_hub()

    log.info("Phase 3 FERTIG. Modell: %s", HF_REPO_MODEL)
