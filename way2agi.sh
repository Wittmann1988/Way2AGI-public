#!/bin/bash
# Way2AGI TUI Launcher
# Usage: ./way2agi.sh [command]
# Commands: chat, models, settings, memory, orchestrator, sysmon, mcp, doctor

cd "$(dirname "$0")" || cd ~/repos/Way2AGI

# Install dependencies quietly
pip install textual aiohttp httpx rich click --quiet 2>/dev/null

# Launch TUI
python -m cli "$@"
