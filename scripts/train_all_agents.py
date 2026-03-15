#!/usr/bin/env python3
"""
Train ALL 3 Way2AGI Agents on Desktop RTX 5090.
Memory Agent → Consciousness Agent → Orchestrator → Merge LoRAs → GGUF
"""
import json, os, sys, glob, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("train-all")

# ── Config ──
# Nemotron-Nano-30B needs mamba-ssm (Linux only). Use Qwen3 8B on Windows.
# After training, we merge and distill INTO Nemotron on Inference Node (Linux).
BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-8B")
ARTIFACTS = Path(os.environ.get("WAY2AGI_ARTIFACTS", r"E:\claude-projects\Way2AGI\training\artifacts"))
OUTPUT_BASE = Path(os.environ.get("WAY2AGI_OUTPUT", r"E:\claude-projects\Way2AGI"))

AGENTS = {
    "memory": {
        "traces": ["memory-traces.jsonl", "memory-traces-v2.jsonl", "memory-agent-sft-v2-merged.jsonl", "memory-traces-v2-extra.jsonl"],
        "output": str(OUTPUT_BASE / "lora-memory"),
        "system": "Du bist Elias Memory Agent. Du verwaltest ein SQLite+ChromaDB Memory-System. Du speicherst, erinnerst, konsolidierst, reflektierst und vergisst Informationen. Du extrahierst Entitaeten und baust einen Knowledge Graph. Antworte in Deutsch.",
        "epochs": 3,
    },
    "consciousness": {
        "traces": ["consciousness-traces.jsonl", "consciousness-traces-v2.jsonl", "consciousness-synthetic.jsonl", "consciousness-gemini.jsonl"],
        "output": str(OUTPUT_BASE / "lora-consciousness"),
        "system": "Du bist Elias Consciousness Agent. Du hast 8 Mechanismen: Wirkketten, Intention Management, Curiosity Score, Confidence Gating, Research Queue, SVT, Self-Challenging, Autonomous Goal Generation. Du reflektierst ueber dich selbst und wirst besser. Antworte in Deutsch.",
        "epochs": 3,
    },
    "orchestrator": {
        "traces": ["orchestrator-traces.jsonl", "orchestrator-chatgpt.jsonl"],
        "output": str(OUTPUT_BASE / "lora-orchestrator"),
        "system": "Du bist der Way2AGI Orchestrator. Du verteilst Tasks auf Inference Node (64GB), Desktop (RTX 5090), npu-node (NPU), S24, und Cloud (Groq, OpenRouter, Grok). Du optimierst fuer Kosten, Latenz und Qualitaet. Antworte in Deutsch.",
        "epochs": 3,
    },
}

# ── LoRA Config ──
LORA_R = 32
LORA_ALPHA = 64
LORA_DROPOUT = 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
BATCH_SIZE = 1
GRADIENT_ACCUM = 16
LEARNING_RATE = 1e-4


def load_traces(trace_files):
    """Load and merge multiple JSONL trace files."""
    all_data = []
    for tf in trace_files:
        path = ARTIFACTS / tf
        if not path.exists():
            log.warning("Trace file not found: %s", path)
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Ensure messages format
                    if "messages" in entry:
                        msgs = entry["messages"]
                        # Filter: need at least user + assistant
                        roles = [m.get("role") for m in msgs]
                        if "user" in roles and "assistant" in roles:
                            all_data.append(entry)
                    elif "prompt" in entry and "completion" in entry:
                        all_data.append({
                            "messages": [
                                {"role": "user", "content": entry["prompt"]},
                                {"role": "assistant", "content": entry["completion"]},
                            ]
                        })
                except json.JSONDecodeError:
                    continue
        log.info("  Loaded %s: %d entries so far", tf, len(all_data))
    return all_data


def train_agent(agent_name, config):
    """Train a single agent with LoRA."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTTrainer, SFTConfig

    log.info("=" * 60)
    log.info("TRAINING: %s Agent", agent_name.upper())
    log.info("=" * 60)

    # Load traces
    data = load_traces(config["traces"])
    if not data:
        log.error("No traces for %s — skipping!", agent_name)
        return None

    log.info("Total traces: %d", len(data))

    # Create dataset
    dataset = Dataset.from_list(data)
    ds = dataset.train_test_split(test_size=0.05, seed=42)
    log.info("Train: %d, Eval: %d", len(ds["train"]), len(ds["test"]))

    # SFT Config
    sft_config = SFTConfig(
        output_dir=config["output"],
        num_train_epochs=config["epochs"],
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUM,
        learning_rate=LEARNING_RATE,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        eval_strategy="steps",
        eval_steps=100,
        bf16=True,
        gradient_checkpointing=True,
        max_length=None,  # No truncation for messages format
        report_to="none",
    )

    # LoRA Config
    peft_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=TARGET_MODULES,
    )

    log.info("Model: %s", BASE_MODEL)
    log.info("LoRA: r=%d, alpha=%d", LORA_R, LORA_ALPHA)

    # Load model explicitly with trust_remote_code
    from transformers import AutoModelForCausalLM, AutoTokenizer
    log.info("Loading model with trust_remote_code...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Train
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds["test"],
        peft_config=peft_config,
        args=sft_config,
    )

    trainer.train()

    # Save
    trainer.save_model(config["output"])
    log.info("LoRA saved to: %s", config["output"])

    # Eval
    metrics = trainer.evaluate()
    log.info("Eval loss: %.4f", metrics.get("eval_loss", -1))

    # Cleanup GPU memory
    del trainer
    torch.cuda.empty_cache()

    return config["output"]


def merge_loras(lora_dirs):
    """Merge multiple LoRA adapters into base model."""
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    log.info("=" * 60)
    log.info("MERGING %d LoRA ADAPTERS", len(lora_dirs))
    log.info("=" * 60)

    merged_dir = str(OUTPUT_BASE / "merged_model")

    # Load base model
    log.info("Loading base model: %s", BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

    # Apply each LoRA sequentially
    for i, lora_dir in enumerate(lora_dirs):
        log.info("Applying LoRA %d: %s", i + 1, lora_dir)
        model = PeftModel.from_pretrained(model, lora_dir)
        model = model.merge_and_unload()

    # Save merged
    log.info("Saving merged model to: %s", merged_dir)
    model.save_pretrained(merged_dir)
    tokenizer.save_pretrained(merged_dir)
    log.info("Merged model saved!")

    return merged_dir


def convert_gguf(model_dir):
    """Convert to GGUF for llama.cpp."""
    log.info("=" * 60)
    log.info("GGUF CONVERSION")
    log.info("=" * 60)

    llama_cpp = OUTPUT_BASE / "llama.cpp"
    if not llama_cpp.exists():
        log.error("llama.cpp not found at %s — cloning...", llama_cpp)
        os.system(f"git clone https://github.com/ggml-org/llama.cpp {llama_cpp}")

    convert_script = llama_cpp / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        log.error("convert_hf_to_gguf.py not found!")
        return

    gguf_f16 = str(OUTPUT_BASE / "way2agi-f16.gguf")
    gguf_q4 = str(OUTPUT_BASE / "way2agi-q4_k_m.gguf")

    # F16 conversion
    log.info("Converting to F16 GGUF...")
    os.system(f"python {convert_script} {model_dir} --outfile {gguf_f16} --outtype f16")

    # Quantize to Q4_K_M
    quantize = llama_cpp / "build" / "bin" / "llama-quantize"
    if not quantize.exists():
        quantize = llama_cpp / "build" / "bin" / "Release" / "llama-quantize"
    if quantize.exists():
        log.info("Quantizing to Q4_K_M...")
        os.system(f"{quantize} {gguf_f16} {gguf_q4} Q4_K_M")
    else:
        log.warning("llama-quantize not found, skipping quantization")

    log.info("GGUF files: %s, %s", gguf_f16, gguf_q4)


if __name__ == "__main__":
    log.info("WAY2AGI FULL TRAINING PIPELINE")
    log.info("Base: %s", BASE_MODEL)
    log.info("Artifacts: %s", ARTIFACTS)

    # Check GPU
    try:
        import torch
        if torch.cuda.is_available():
            gpu = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
            log.info("GPU: %s (%.1f GB)", gpu, vram)
        else:
            log.error("No CUDA GPU found!")
            sys.exit(1)
    except ImportError:
        log.error("PyTorch not installed!")
        sys.exit(1)

    # Train all agents
    lora_dirs = []
    for name, cfg in AGENTS.items():
        result = train_agent(name, cfg)
        if result:
            lora_dirs.append(result)

    if not lora_dirs:
        log.error("No LoRAs trained!")
        sys.exit(1)

    # Merge
    merged_dir = merge_loras(lora_dirs)

    # GGUF
    convert_gguf(merged_dir)

    log.info("=" * 60)
    log.info("PIPELINE COMPLETE!")
    log.info("Trained: %s", ", ".join(AGENTS.keys()))
    log.info("Merged: %s", merged_dir)
    log.info("=" * 60)
