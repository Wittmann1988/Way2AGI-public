#\!/bin/bash
# Backup aller Claude Session-Transkripte
BACKUP_DIR="/opt/way2agi/backups/sessions"
mkdir -p "$BACKUP_DIR"

# Lokale primary-node Sessions
cp -u /home/YOUR_USER/.claude/projects/*/????????-????-????-????-????????????.jsonl "$BACKUP_DIR/" 2>/dev/null

# Backup der DB statt der Sessions (Tablet nicht direkt erreichbar)
cp -u /opt/way2agi/memory/db/elias_memory.db "$BACKUP_DIR/elias_memory_$(date +%Y%m%d).db" 2>/dev/null

# Aufraumen: Nur die letzten 30 DB-Backups behalten
ls -t "$BACKUP_DIR"/elias_memory_*.db 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null

echo "$(date): Backup OK — $(ls "$BACKUP_DIR"/*.jsonl 2>/dev/null | wc -l) Sessions, $(ls "$BACKUP_DIR"/*.db 2>/dev/null | wc -l) DB-Backups"
