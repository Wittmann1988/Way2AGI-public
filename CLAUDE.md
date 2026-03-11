# Way2AGI — CLAUDE.md

## Project

Way2AGI is a self-improving AI system that thinks about itself, remembers, and grows.
It combines local LLM orchestration, persistent memory, autonomous agents, and continuous training.

## Architecture

```
Way2AGI/
├── automation/          # Autonomous cronjobs (GoalGuard, Research, Roundtable, Training)
│   ├── cronjobs/        # Python scripts for crontab
│   └── crontab.conf     # Installed cronjobs (controller node)
├── compute/             # Node Daemons (Controller, Desktop, Laptop, Mobile)
├── memory/              # Memory system (SQLite + ChromaDB)
│   ├── db/              # Database
│   ├── migrations/      # Schema migrations
│   └── src/             # Memory API
├── orchestrator/        # Task decomposition, Model routing, Composer
│   └── src/             # Registry, Composer, Cache, Resilience
├── training/            # Model Build Pipeline (requires GPU)
│   └── src/             # abliterate, distill, train_sft, publish, convert_gguf, pipeline
├── research/            # arXiv + GitHub Scraper, Analysis pipeline
├── docs/                # Documentation
│   ├── plans/           # Design docs and migration plans
│   ├── roundtables/     # Roundtable protocols (all models)
│   └── rules/           # User rules (immutable)
├── cli/                 # Terminal UI
├── gateway/             # API Gateway
├── cognition/           # Drives, Goals
├── canvas/              # Visualization
└── channels/            # Telegram etc.
```

## Compute Network

Way2AGI supports a multi-node compute network. Configure your nodes in `.env`:

| Node | Env Var | Port | Role | Example Models |
|------|---------|------|------|----------------|
| Controller | CONTROLLER_IP | 8050 | Controller, Memory, Always-On | lfm2:24b, nemotron, smallthinker |
| Desktop | DESKTOP_IP | 8100 | Heavy Compute, Training | lfm2:24b, qwen3.5:9b |
| Laptop | LAPTOP_IP | 8150 | Orchestration Server, Agents | lfm2:24b, smallthinker |
| Mobile | MOBILE_IP | 8200 | Lite, Verification | qwen3:1.7b |

## Setup

1. Copy `.env.example` to `.env` and fill in your values
2. Configure SSH access to your compute nodes (use SSH keys, not passwords)
3. Install dependencies: `pip install -e .` and `pnpm install`
4. Start the memory server: `python -m memory.src.server`
5. Start compute daemons on each node

## Rules System

See `docs/rules/example-rules.md` for an example rule set.
Rules are stored in the database (rules table) and enforced by GoalGuard.

## Cronjobs (autonomous, on controller node)

| Time | Job | Purpose |
|------|-----|---------|
| 07:00 | research.py | Scrape arXiv + GitHub |
| 08:00/14:00/20:00 | goalguard.py | Check rules, process TODOs |
| 12:00 | roundtable.py | Send research findings to all models |
| 16:00 | implement.py | Implement TODOs as code |
| every 5 days 02:00 | training.py | SFT/DPO on GPU node |

## DB Schema

SQLite: `memory/db/memory.db`
Tables: memories, entities, relations, goals, errors, todos, milestones, endgoal, rules, action_log, meta, model_evaluations, traces, eval_results, identity_vault, and more.
Migration: `memory/migrations/001_add_new_tables.sql`

## Commands

```bash
# SSH to controller
ssh YOUR_CONTROLLER

# GoalGuard manual run
python3 automation/cronjobs/goalguard.py

# Memory
python -m memory.src.server

# Ollama
curl http://localhost:11434/api/tags

# Model Build Pipeline (on GPU node)
python -m training.src.pipeline --all          # All 5 phases
python -m training.src.pipeline --phase 2      # Only Distillation
python scripts/build_model.py --phase 3        # Convenience wrapper
```

## Training Pipeline

5-phase pipeline for custom model training (requires GPU):
1. **PRISM Abliteration** — Remove refusal mechanisms
2. **Knowledge Distillation** — Collect traces from multiple LLMs
3. **SFT Training** — LoRA on abliterated model
4. **Publish** — Model Card + Push to HuggingFace
5. **GGUF** — Conversion for llama.cpp/Ollama (Q4_K_M, Q6_K, Q8_0)

Config: `training/src/config.py` | Artifacts: `training/artifacts/`

## Environment Variables

See `.env.example` for all required configuration.
