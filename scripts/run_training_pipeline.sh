#!/bin/bash
# Way2AGI Training Pipeline — Autonomer 5-Phasen-Prozess
# Phase 1 (Distillation): Laeuft auf primary-node (Cloud-API-Traces sammeln)
# Phase 2-4 (Abliteration, SFT, GGUF): Laeuft auf Desktop RTX 5090 via SSH+WSL2
# Phase 5 (Deploy): GGUF auf Inference Node kopieren und aktivieren
#
# Cronjob: alle 5 Tage, 02:00 nachts
# Manuelle Ausfuehrung: bash /opt/way2agi/Way2AGI/scripts/run_training_pipeline.sh
set -euo pipefail

# Lade API-Keys
set -a && . /opt/way2agi/.env && set +a

WAYROOT="/opt/way2agi/Way2AGI"
LOG_DIR="${WAYROOT}/logs"
LOG="${LOG_DIR}/training_pipeline.log"
DESKTOP="YOUR_USER@YOUR_COMPUTE_NODE_IP"
INFERENCE_NODE="inference-node"
DESKTOP_STAGING="/tmp/way2agi-pipeline"

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" | tee -a "$LOG"; }

die() { log "FATAL" "$1"; exit 1; }

check_ssh() {
    local host="$1" label="$2"
    if ! ssh -o ConnectTimeout=10 "$host" "echo OK" >/dev/null 2>&1; then
        die "$label nicht erreichbar via SSH"
    fi
    log "INFO" "$label SSH OK"
}

# ═══════════════════════════════════════════════════════════
log "INFO" "═══════════════════════════════════════════════════════"
log "INFO" "WAY2AGI TRAINING PIPELINE — START"
log "INFO" "═══════════════════════════════════════════════════════"

# Voraussetzungen pruefen
check_ssh "$DESKTOP" "Desktop (RTX 5090)"
check_ssh "$INFERENCE_NODE" "Inference Node"

# ── Phase 1: Distillation (lokal auf primary-node) ──────────
log "INFO" "PHASE 1: Knowledge Distillation (Cloud-Traces sammeln)"
log "INFO" "  Provider: Groq, Gemini, OpenAI, xAI, Ollama Cloud"

cd "$WAYROOT"
if python3 -m training.src.pipeline --phase 2 2>&1 | tee -a "$LOG"; then
    log "INFO" "Phase 1 (Distillation) ERFOLGREICH"
else
    log "WARN" "Phase 1 (Distillation) hatte Fehler — fahre trotzdem fort"
fi

TRACES_FILE="${WAYROOT}/training/artifacts/elias-distill-traces/distill_traces.jsonl"
if [ ! -f "$TRACES_FILE" ]; then
    die "Keine Traces gefunden: $TRACES_FILE"
fi
TRACE_COUNT=$(wc -l < "$TRACES_FILE")
log "INFO" "  $TRACE_COUNT Traces vorhanden"

# ── Phase 2: PRISM Abliteration (Desktop, braucht GPU) ─────
log "INFO" "PHASE 2: PRISM Abliteration auf Desktop"

# Staging-Verzeichnis auf Desktop erstellen
ssh "$DESKTOP" "mkdir -p ${DESKTOP_STAGING}" 2>&1 | tee -a "$LOG"

# Pipeline-Source auf Desktop kopieren
log "INFO" "  Kopiere Pipeline-Code auf Desktop..."
rsync -az --delete \
    "${WAYROOT}/training/src/" \
    "${DESKTOP}:${DESKTOP_STAGING}/training_src/" 2>&1 | tee -a "$LOG"

# Abliteration in WSL2 ausfuehren
log "INFO" "  Starte Abliteration in WSL2 (Ubuntu-22.04)..."
ssh "$DESKTOP" "wsl -d Ubuntu-22.04 -- bash -c '
    cd /mnt/c/Users/ee
    export PYTHONPATH=${DESKTOP_STAGING}
    export WAY2AGI_ARTIFACTS=${DESKTOP_STAGING}/artifacts
    mkdir -p \${WAY2AGI_ARTIFACTS}
    python3 -c \"
import sys
sys.path.insert(0, \\\"${DESKTOP_STAGING}/training_src\\\")
import abliterate
abliterate.run()
\"
'" 2>&1 | tee -a "$LOG"

if [ $? -eq 0 ]; then
    log "INFO" "Phase 2 (Abliteration) ERFOLGREICH"
else
    log "WARN" "Phase 2 (Abliteration) FEHLGESCHLAGEN — nutze Base-Model fuer SFT"
fi

# ── Phase 3: SFT Training (Desktop, braucht GPU) ───────────
log "INFO" "PHASE 3: SFT Training auf Desktop"

# Traces auf Desktop kopieren
log "INFO" "  Kopiere Traces auf Desktop..."
rsync -az "${WAYROOT}/training/artifacts/" \
    "${DESKTOP}:${DESKTOP_STAGING}/artifacts/" 2>&1 | tee -a "$LOG"

# SFT in WSL2 ausfuehren
log "INFO" "  Starte SFT Training in WSL2..."
ssh -o ServerAliveInterval=60 "$DESKTOP" "wsl -d Ubuntu-22.04 -- bash -c '
    export PYTHONPATH=${DESKTOP_STAGING}
    export WAY2AGI_ARTIFACTS=${DESKTOP_STAGING}/artifacts
    export HF_TOKEN=\${HF_TOKEN:-}
    python3 -c \"
import sys
sys.path.insert(0, \\\"${DESKTOP_STAGING}/training_src\\\")
import train_sft
train_sft.run()
\"
'" 2>&1 | tee -a "$LOG"

if [ $? -eq 0 ]; then
    log "INFO" "Phase 3 (SFT) ERFOLGREICH"
else
    die "Phase 3 (SFT) FEHLGESCHLAGEN — Pipeline abgebrochen"
fi

# ── Phase 4: GGUF Konvertierung (Desktop) ───────────────────
log "INFO" "PHASE 4: GGUF Konvertierung auf Desktop"

ssh -o ServerAliveInterval=60 "$DESKTOP" "wsl -d Ubuntu-22.04 -- bash -c '
    export PYTHONPATH=${DESKTOP_STAGING}
    export WAY2AGI_ARTIFACTS=${DESKTOP_STAGING}/artifacts
    python3 -c \"
import sys
sys.path.insert(0, \\\"${DESKTOP_STAGING}/training_src\\\")
import convert_gguf
convert_gguf.run()
\"
'" 2>&1 | tee -a "$LOG"

if [ $? -eq 0 ]; then
    log "INFO" "Phase 4 (GGUF) ERFOLGREICH"
else
    die "Phase 4 (GGUF) FEHLGESCHLAGEN"
fi

# ── Phase 5: Deploy auf Inference Node ──────────────────────────────
log "INFO" "PHASE 5: Deploy auf Inference Node"

# GGUF von Desktop holen (primary-node als Relay)
GGUF_FILE=$(ssh "$DESKTOP" "ls -t ${DESKTOP_STAGING}/artifacts/elias-gguf/*.gguf 2>/dev/null | head -1")

if [ -z "$GGUF_FILE" ]; then
    # Versuche Q4_K_M explizit
    GGUF_FILE="${DESKTOP_STAGING}/artifacts/elias-gguf/elias-nemotron-30b-Q4_K_M.gguf"
fi

log "INFO" "  GGUF: $GGUF_FILE"
log "INFO" "  Desktop -> primary-node..."
scp "${DESKTOP}:${GGUF_FILE}" /tmp/elias-nemotron-latest.gguf 2>&1 | tee -a "$LOG"

log "INFO" "  primary-node -> Inference Node..."
scp /tmp/elias-nemotron-latest.gguf "${INFERENCE_NODE}:/opt/way2agi/models/elias-nemotron-latest.gguf" 2>&1 | tee -a "$LOG"

# Symlink aktualisieren und SpecDec neustarten
ssh "$INFERENCE_NODE" "
    cd /opt/way2agi/models
    ln -sf elias-nemotron-latest.gguf nemotron-30b.gguf
    echo 'GGUF deployed: \$(ls -lh elias-nemotron-latest.gguf | awk \"{print \\\$5}\")'
" 2>&1 | tee -a "$LOG"

# Aufraumen
rm -f /tmp/elias-nemotron-latest.gguf

log "INFO" "Phase 5 (Deploy) ERFOLGREICH"

# ═══════════════════════════════════════════════════════════
log "INFO" "═══════════════════════════════════════════════════════"
log "INFO" "PIPELINE FERTIG — $(date '+%Y-%m-%d %H:%M:%S')"
log "INFO" "═══════════════════════════════════════════════════════"
