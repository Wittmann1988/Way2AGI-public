#!/bin/bash
# Start Agent Training on Desktop WSL2
# Usage: ssh desktop 'wsl -d Ubuntu-22.04 -- bash /mnt/c/temp_training/run_agent_train.sh orchestrator'

AGENT=${1:-way2agi-orchestrator}
export WAY2AGI_ROOT=/home/YOUR_USER/Way2AGI
cd $WAY2AGI_ROOT

echo "=== Starting training for $AGENT ==="
echo "GPU:"
python3 -c "import torch; print(f'  {torch.cuda.get_device_name(0)} - CUDA {torch.version.cuda}')" 2>/dev/null

python3 -m training.src.train_agent \
  --agent $AGENT \
  --data training/artifacts/${AGENT#way2agi-}-traces.jsonl \
  --epochs 3 \
  --lr 2e-4

echo "=== Training complete for $AGENT ==="
