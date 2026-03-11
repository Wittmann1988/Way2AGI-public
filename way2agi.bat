@echo off
REM Way2AGI TUI Launcher for Windows Desktop
REM Usage: way2agi.bat [command]
REM Commands: chat, models, settings, memory, orchestrator, sysmon, mcp, doctor

cd /d E:\claude-projects\Way2AGI
pip install textual aiohttp httpx rich click --quiet 2>nul
python -m cli %*
