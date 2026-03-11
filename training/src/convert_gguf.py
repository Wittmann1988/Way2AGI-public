"""
Phase 5: GGUF Konvertierung — Konvertiert trainiertes Modell fuer llama.cpp/Ollama.
Quantisierungen: Q4_K_M, Q6_K, Q8_0.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import GGUF_OUTPUT_DIR, GGUF_QUANTS, HF_REPO_GGUF, SFT_OUTPUT_DIR

log = logging.getLogger("elias-build")


def run():
    """Konvertiert Modell nach GGUF und laedt zu HuggingFace hoch."""
    log.info("=" * 60)
    log.info("PHASE 5: GGUF KONVERTIERUNG")
    log.info("=" * 60)

    os.makedirs(GGUF_OUTPUT_DIR, exist_ok=True)
    merged_dir = os.path.join(GGUF_OUTPUT_DIR, "merged")

    # Merge LoRA + Base Model
    log.info("Merge LoRA Adapter mit Base Model...")
    merge_script = '''
import torch
from peft import AutoPeftModelForCausalLM
from transformers import AutoTokenizer

model = AutoPeftModelForCausalLM.from_pretrained(
    "{sft_dir}",
    torch_dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
merged = model.merge_and_unload()
merged.save_pretrained("{merged_dir}", safe_serialization=True)

tokenizer = AutoTokenizer.from_pretrained("{sft_dir}")
tokenizer.save_pretrained("{merged_dir}")
print("Merged model saved to {merged_dir}")
'''.format(sft_dir=SFT_OUTPUT_DIR, merged_dir=merged_dir)

    merge_file = Path(GGUF_OUTPUT_DIR) / "merge_lora.py"
    merge_file.write_text(merge_script)
    subprocess.run([sys.executable, str(merge_file)], check=True)

    # GGUF Konvertierung
    log.info("Konvertiere nach GGUF...")
    for quant in GGUF_QUANTS:
        output_name = "elias-nemotron-30b-%s.gguf" % quant
        output_path = Path(GGUF_OUTPUT_DIR) / output_name
        log.info("  Erstelle %s...", output_name)

        try:
            subprocess.run([
                sys.executable, "-m", "llama_cpp.convert",
                "--outfile", str(output_path),
                "--outtype", quant.lower(),
                merged_dir,
            ], check=True, capture_output=True)
            log.info("  %s erstellt: %.1f GB", output_name, output_path.stat().st_size / 1e9)
        except Exception as e:
            log.warning("  %s fehlgeschlagen: %s", quant, e)
            try:
                subprocess.run([
                    "python", "llama.cpp/convert_hf_to_gguf.py",
                    merged_dir,
                    "--outfile", str(output_path),
                    "--outtype", quant.lower(),
                ], check=True)
                log.info("  %s erstellt (alt. Methode)", output_name)
            except Exception as e2:
                log.error("  %s FEHLGESCHLAGEN: %s", quant, e2)

    # Upload zu HuggingFace
    log.info("Lade GGUF zu HuggingFace: %s", HF_REPO_GGUF)
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(HF_REPO_GGUF, exist_ok=True)
        for gguf_file in Path(GGUF_OUTPUT_DIR).glob("*.gguf"):
            api.upload_file(
                path_or_fileobj=str(gguf_file),
                path_in_repo=gguf_file.name,
                repo_id=HF_REPO_GGUF,
            )
            log.info("  Hochgeladen: %s", gguf_file.name)
    except Exception as e:
        log.warning("GGUF Upload fehlgeschlagen: %s", e)

    log.info("Phase 5 FERTIG. GGUF Dateien: %s", GGUF_OUTPUT_DIR)
