# Way2AGI Training — Anleitung fuer PC

## Kontext

Dies ist das Way2AGI Projekt (GitHub: YOUR_GITHUB_USER/Way2AGI).
the user entwickelt ein selbstverbesserndes AI-System.
Training-Daten (129 SFT + 15 DPO Beispiele) sind bereits auf HuggingFace.

## Schnellstart

### 1. Dependencies installieren
```bash
pip install trl peft transformers accelerate datasets torch huggingface-hub sentencepiece protobuf gguf
```

### 2. HuggingFace Login
```bash
huggingface-cli login  # Token: siehe ~/.bashrc HF_TOKEN
```

### 3. Repo klonen
```bash
git clone https://github.com/YOUR_GITHUB_USER/Way2AGI.git
cd Way2AGI
```

### 4. SFT Training starten
```bash
python scripts/train_on_pc.py
```
- Trainiert Qwen2.5-3B-Instruct mit LoRA
- Dataset: YOUR_HF_USER/way2agi-traces (129 Beispiele, 6 Domains)
- Pushed automatisch zu YOUR_HF_USER/way2agi-model

### 5. GGUF konvertieren
```bash
python scripts/convert_gguf.py
```
- Merged LoRA + Base Model
- Konvertiert zu GGUF (F16 + Q4_K_M)
- Uploaded zu YOUR_HF_USER/way2agi-model-GGUF

## Fuer Claude Code auf dem PC

Falls eine Claude-Instanz das ausfuehren soll:

```
Fuehre folgendes aus:
1. pip install trl peft transformers accelerate datasets torch huggingface-hub
2. huggingface-cli login  # Token: siehe ~/.bashrc HF_TOKEN
3. git clone https://github.com/YOUR_GITHUB_USER/Way2AGI.git && cd Way2AGI
4. python scripts/train_on_pc.py
5. Nach Abschluss: python scripts/convert_gguf.py
```

## Projekt-Infos

- GitHub: https://github.com/YOUR_GITHUB_USER/Way2AGI
- HF User: YOUR_HF_USER
- Dataset: https://huggingface.co/datasets/YOUR_HF_USER/way2agi-traces
- Zielmodell: https://huggingface.co/YOUR_HF_USER/way2agi-model
- GGUF: https://huggingface.co/YOUR_HF_USER/way2agi-model-GGUF
