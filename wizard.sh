#!/bin/bash
echo "=== Way2AGI First-Run Wizard ==="
echo "Way2AGI is not what it is — it's what it becomes."

# 1. Ordner anlegen
mkdir -p user core
echo "user/" >> .gitignore

# 2. Config kopieren
cp .env.example user/.env 2>/dev/null || true

# 3. Hardware-Auto-Discovery
echo "Hardware wird erkannt..."
echo "CONTROLLER_IP=$(hostname -I | awk '{print $1}')" >> user/.env

# 4. Identity + Goal
read -p "Wie soll dein KI-Partner heißen? " name
echo "USER_MODEL_PREFIX=$name" >> user/.env
read -p "Was soll Way2AGI für dich werden? (z.B. 'mein ERP-System') " goal

# 5. Resource Budget
read -p "Max GPU-Stunden pro Tag? [8] " gpuh
echo "MAX_GPU_HOURS_PER_DAY=${gpuh:-8}" >> user/.env

echo "Wizard fertig! Starte jetzt mit: python -m core.node_daemon"
