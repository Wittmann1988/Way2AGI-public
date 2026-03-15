#!/bin/bash
cd /opt/way2agi/Way2AGI || exit 1

# Nur committen wenn es Aenderungen gibt
CHANGES=$(git status --short | wc -l)
if [ "$CHANGES" -eq 0 ]; then
    echo "$(date): Keine Aenderungen"
    exit 0
fi

TIMESTAMP=$(date +%Y-%m-%d\ %H:%M)

git add -A
git commit -m "auto: ${TIMESTAMP} — ${CHANGES} files changed

Autonomous changes by Way2AGI Agent Loop + Cronjobs.
Co-Authored-By: Way2AGI Agent Loop <noreply@way2agi.dev>"

git push origin main 2>&1

echo "$(date): $CHANGES files committed + pushed"
