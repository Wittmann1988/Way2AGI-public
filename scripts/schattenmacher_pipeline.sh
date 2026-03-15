#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
CHANNEL_URL="https://www.youtube.com/@derschattenmacher5501/videos"
DOWNLOAD_DIR="/opt/way2agi/training_data/schattenmacher/audio"
TRANSCRIPT_DIR="/opt/way2agi/Way2AGI/training/data/schattenmacher"
LOG="/opt/way2agi/Way2AGI/logs/schattenmacher.log"

# Lade .env fuer GROQ_API_KEY
set -a && . /opt/way2agi/.env && set +a

mkdir -p "$DOWNLOAD_DIR" "$TRANSCRIPT_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG"; }
log "=== PIPELINE START ==="

# Phase 1: Video-URLs
log "Sammle URLs..."
yt-dlp --flat-playlist --print "%(id)s %(title)s" "$CHANNEL_URL" > "$DOWNLOAD_DIR/video_list.txt" 2>/dev/null
TOTAL=$(wc -l < "$DOWNLOAD_DIR/video_list.txt")
log "$TOTAL Videos gefunden"

# Phase 2: Audio Download + Transkription (nur neue)
INDEX=0
while read -r LINE; do
    ID="$(echo "$LINE" | cut -d" " -f1)"
    TITLE="$(echo "$LINE" | cut -d" " -f2-)"
    INDEX=$((INDEX+1))
    TRANSCRIPT="$TRANSCRIPT_DIR/${ID}.txt"
    [ -f "$TRANSCRIPT" ] && continue  # Skip wenn bereits transkribiert
    
    log "[$INDEX/$TOTAL] $TITLE"
    AUDIO="$DOWNLOAD_DIR/${ID}.mp3"
    
    # Download Audio only
    yt-dlp -x --audio-format mp3 -o "$AUDIO" "https://youtube.com/watch?v=$ID" 2>/dev/null || { log "  SKIP (Download fail)"; continue; }
    
    # Groq Whisper Transkription
    FILESIZE=$(stat -c%s "$AUDIO" 2>/dev/null || echo 0)
    if [ "$FILESIZE" -gt 25000000 ]; then
        log "  SKIP (>25MB, muss gesplittet werden)"
        continue
    fi
    
    curl -s -X POST "https://api.groq.com/openai/v1/audio/transcriptions" \
        -H "Authorization: Bearer $GROQ_API_KEY" \
        -F "model=whisper-large-v3-turbo" \
        -F "file=@$AUDIO" \
        -F "language=de" \
        --max-time 120 > "$TRANSCRIPT" 2>/dev/null
    
    if [ -s "$TRANSCRIPT" ]; then
        log "  OK ($(wc -c < "$TRANSCRIPT") bytes)"
    else
        log "  FAIL (leeres Transkript)"
        rm -f "$TRANSCRIPT"
    fi
    
    rm -f "$AUDIO"  # Audio loeschen nach Transkription
    sleep 3  # Rate Limit
done < "$DOWNLOAD_DIR/video_list.txt"

log "=== PIPELINE FERTIG: $(ls "$TRANSCRIPT_DIR"/*.txt 2>/dev/null | wc -l) Transkripte ==="
