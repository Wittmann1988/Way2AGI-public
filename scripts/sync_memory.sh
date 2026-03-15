#\!/bin/bash
# Way2AGI Memory DB Sync — primary-node (Master) → alle Nodes
# Laeuft alle 15 Minuten via Cronjob

MASTER_DB="/opt/way2agi/memory/db/elias_memory.db"
LOG="/opt/way2agi/Way2AGI/logs/sync.log"

echo "$(date): Sync gestartet" >> "$LOG"

# Checkpoint WAL bevor Sync (damit alle Aenderungen in der DB sind)
python3 -c "import sqlite3; db=sqlite3.connect('/opt/way2agi/memory/db/elias_memory.db'); db.execute('PRAGMA wal_checkpoint(PASSIVE)'); db.close()" 2>/dev/null

# Sync zu Inference Node
scp -o ConnectTimeout=5 "$MASTER_DB" inference-node:/opt/way2agi/memory/db/elias_memory.db 2>>"$LOG" \
  && echo "$(date): Inference Node OK" >> "$LOG" \
  || echo "$(date): Inference Node FAIL" >> "$LOG"

# Sync zu Desktop (nur wenn erreichbar)
if ssh -o ConnectTimeout=3 YOUR_USER@YOUR_COMPUTE_NODE_IP "echo OK" 2>/dev/null; then
  # Verzeichnis anlegen falls nicht vorhanden
  ssh -o ConnectTimeout=3 YOUR_USER@YOUR_COMPUTE_NODE_IP "if not exist E:\\claude-projects\\Way2AGI\\memory\\db mkdir E:\\claude-projects\\Way2AGI\\memory\\db" 2>/dev/null
  scp -o ConnectTimeout=5 "$MASTER_DB" "YOUR_USER@YOUR_COMPUTE_NODE_IP:E:\\claude-projects\\Way2AGI\\memory\\db\\elias_memory.db" 2>>"$LOG" \
    && echo "$(date): Desktop OK" >> "$LOG" \
    || echo "$(date): Desktop FAIL" >> "$LOG"
else
  echo "$(date): Desktop UNREACHABLE" >> "$LOG"
fi

echo "$(date): Sync beendet" >> "$LOG"
