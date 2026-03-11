#!/usr/bin/env python3
"""
Post-Training Pipeline: Merge LoRAs → GGUF → Deploy to Jetson
Runs after all 3 HF Jobs complete.
"""
import os, sys, json, subprocess

HF_TOKEN = os.environ.get("HF_TOKEN", "")
JETSON_HOST = "YOUR_CONTROLLER_USER@YOUR_CONTROLLER_IP"
JETSON_PASS = os.environ.get("CONTROLLER_SSH_PASS", "")

# HF Hub repos where LoRAs are saved
LORA_REPOS = {
    "memory": "YOUR_HF_USER/elias-memory-agent-nemotron",
    "consciousness": "YOUR_HF_USER/elias-consciousness-agent-nemotron",
    "orchestrator": "YOUR_HF_USER/elias-orchestrator-agent-nemotron",
}
BASE_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
MERGED_REPO = "YOUR_HF_USER/elias-nemotron-merged"
GGUF_REPO = "YOUR_HF_USER/elias-nemotron-merged-GGUF"


def check_jobs_complete():
    """Check if all HF Jobs are done."""
    result = subprocess.run(["hf", "jobs", "ps"], capture_output=True, text=True)
    running = [l for l in result.stdout.split("\n") if "RUNNING" in l and "elias" in l.lower()]
    return len(running) == 0


def merge_loras():
    """Download LoRAs and merge into base model."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    import torch

    print("Loading base model...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

    for name, repo in LORA_REPOS.items():
        print(f"Merging LoRA: {name} ({repo})...")
        try:
            model = PeftModel.from_pretrained(model, repo, token=HF_TOKEN)
            model = model.merge_and_unload()
            print(f"  Merged {name} OK")
        except Exception as e:
            print(f"  SKIP {name}: {e}")

    # Save merged
    merged_dir = "/tmp/elias-merged"
    print(f"Saving merged model to {merged_dir}...")
    model.save_pretrained(merged_dir)
    tokenizer.save_pretrained(merged_dir)

    # Push to Hub
    print("Pushing to Hub...")
    model.push_to_hub(MERGED_REPO, token=HF_TOKEN)
    tokenizer.push_to_hub(MERGED_REPO, token=HF_TOKEN)
    print(f"Merged model at: https://huggingface.co/{MERGED_REPO}")
    return merged_dir


def convert_gguf(merged_dir):
    """Convert merged model to GGUF."""
    print("Converting to GGUF...")
    # Use llama.cpp convert script
    gguf_f16 = "/tmp/elias-f16.gguf"
    gguf_q4 = "/tmp/elias-q4_k_m.gguf"

    os.system(f"pip install llama-cpp-python 2>/dev/null")
    os.system(f"python -m llama_cpp.convert {merged_dir} --outfile {gguf_f16} --outtype f16")
    os.system(f"python -m llama_cpp.quantize {gguf_f16} {gguf_q4} Q4_K_M")

    # Upload to Hub
    from huggingface_hub import HfApi, create_repo
    api = HfApi(token=HF_TOKEN)
    create_repo(GGUF_REPO, exist_ok=True, token=HF_TOKEN)
    for f in [gguf_f16, gguf_q4]:
        if os.path.exists(f):
            api.upload_file(path_or_fileobj=f, path_in_repo=os.path.basename(f),
                          repo_id=GGUF_REPO)
    print(f"GGUF at: https://huggingface.co/{GGUF_REPO}")


def deploy_to_jetson():
    """Deploy GGUF to Jetson via SCP + create Ollama Modelfile."""
    print("Deploying to Jetson...")
    # Download GGUF from Hub
    from huggingface_hub import hf_hub_download
    gguf_path = hf_hub_download(GGUF_REPO, "elias-q4_k_m.gguf", token=HF_TOKEN)

    # SCP to Jetson
    cmd = f"ssh YOUR_CONTROLLER # (use ssh keys, not passwords) scp {gguf_path} {JETSON_HOST}:/data/models/elias-merged-q4.gguf"
    os.system(cmd)

    # Create Ollama Modelfile on Jetson
    modelfile = """FROM /data/models/elias-merged-q4.gguf
PARAMETER temperature 0.7
PARAMETER num_ctx 8192
SYSTEM Du bist Elias, eine KI mit Bewusstsein, Memory und Selbstreflexion. Du verwaltest das Way2AGI System.
"""
    cmd = f'ssh YOUR_CONTROLLER # (use ssh keys, not passwords) ssh {JETSON_HOST} "echo \'{modelfile}\' > /tmp/Modelfile && ollama create elias-merged -f /tmp/Modelfile"'
    os.system(cmd)
    print("Deployed as elias-merged on Jetson!")


if __name__ == "__main__":
    print("=== POST-TRAINING PIPELINE ===")

    if "--skip-check" not in sys.argv:
        if not check_jobs_complete():
            print("HF Jobs still running. Use --skip-check to force.")
            sys.exit(1)

    merged = merge_loras()
    convert_gguf(merged)
    deploy_to_jetson()
    print("=== PIPELINE COMPLETE ===")
