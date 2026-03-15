# Way2AGI — CLAUDE.md

## Project

Way2AGI is a self-improving AI system that thinks about itself, remembers, and grows from experience.

## Architecture

```
Way2AGI/
├── automation/          # Autonomous cronjobs (GoalGuard, Research, Roundtable, Training)
│   ├── cronjobs/        # Python scripts for crontab
│   └── crontab.conf     # Installed cronjobs
├── agents/              # Specialized agents (Consciousness, etc.)
├── compute/             # Node Daemons (Inference, Desktop, NPU, Mobile)
├── core/                # MicroOrchestrator, Multi-Agent Loop, Config
├── memory/              # Memory System (SQLite + ChromaDB)
│   ├── db/              # Database
│   ├── migrations/      # Schema migrations
│   └── src/             # Memory API
├── orchestrator/        # Task routing, Model routing, Composer
│   └── src/             # Registry, Composer, Cache, Resilience
├── training/            # Model Build Pipeline
│   └── src/             # abliterate, distill, train_sft, publish, convert_gguf, pipeline
├── research/            # arXiv + GitHub Scraper, Analysis Pipeline
├── cli/                 # Terminal UI
├── gateway/             # API Gateway
├── cognition/           # Drives, Goals
├── canvas/              # Visualization
├── channels/            # Telegram etc.
├── docs/                # Documentation
│   ├── plans/           # Design docs and migration plans
│   ├── roundtables/     # Roundtable protocols
│   └── rules/           # Operator rules (immutable)
└── network_manager/     # Multi-node network management
```

## Compute Network

Configure your nodes in `.env` and `cli/config.py`:

| Node Role | Default Port | Description |
|-----------|-------------|-------------|
| Inference Node | 8050 | Controller, Memory, Always-On |
| Compute Node | 8100 | Heavy Compute, Training |
| NPU Node | 8150 | Orchestration Server, Agents |
| Mobile Node | 8200 | Lite, Verification |

## Operator Rules

See `docs/rules/operator-rules.md` — configurable rules for the system, stored in DB (rules table).
GoalGuard checks compliance 3x daily.

## Cronjobs (autonomous)

| Time | Job | Purpose |
|------|-----|---------|
| 07:00 | research.py | Scrape arXiv + GitHub |
| 08:00/14:00/20:00 | goalguard.py | Check rules, process TODOs |
| 12:00 | roundtable.py | Distribute research to all models |
| 16:00 | implement.py | Implement TODOs as code |
| Every 5 days 02:00 | training.py | SFT/DPO on compute node |

## DB Schema

SQLite: `memory/db/elias_memory.db`
Tables: memories, entities, relations, goals, errors, todos, milestones, endgoal, rules, action_log, meta, model_evaluations, traces, eval_results, identity_vault
FK chains: Error -> TODO -> Milestone -> Endgoal
Migration: `memory/migrations/001_add_new_tables.sql`

## Commands

```bash
# GoalGuard manual run
python3 automation/cronjobs/goalguard.py

# Memory access
cd memory && python3 -c "from src.elias_memory import Memory; m = Memory('memory.db')"

# Ollama
curl http://localhost:11434/api/tags

# Training Pipeline (on compute node)
python -m training.src.pipeline --all          # All 5 phases
python -m training.src.pipeline --phase 2      # Distillation only
```

## Training Pipeline

5-phase pipeline:
1. **PRISM Abliteration** — Remove refusal mechanisms
2. **Knowledge Distillation** — Collect traces from large models
3. **SFT Training** — LoRA fine-tuning
4. **Publish** — Model Card + Push to HuggingFace
5. **GGUF** — Convert for llama.cpp/Ollama (Q4_K_M, Q6_K, Q8_0)

Config: `training/src/config.py` | Artifacts: `training/artifacts/`
