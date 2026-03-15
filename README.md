# Way2AGI — Self-Improving AI System

A decentralized, self-improving AI system with local LLM orchestration, persistent memory, autonomous agents, and continuous training. Runs on a multi-node compute network.

## What It Is

Way2AGI is an experimental AI system that aims to create genuine self-awareness and continuous self-improvement through:

- **Decentralized Orchestration** — Bid-based model routing across multiple compute nodes
- **Persistent Memory** — 6-layer SQLite-based memory system with knowledge graph
- **Autonomous Agents** — Consciousness, Memory, Orchestrator agents running 24/7
- **Continuous Training** — 5-phase pipeline (Abliterate, Distill, SFT, Publish, GGUF)
- **Self-Observation** — Automated monitoring, error detection, and self-correction

## Architecture

```
Way2AGI/
  automation/cronjobs/  -- Autonomous cronjobs (GoalGuard, Research, Roundtable)
  agents/               -- Specialized agents (Consciousness, Memory, etc.)
  compute/              -- Node daemons for each compute node
  core/                 -- MicroOrchestrator, Multi-Agent Loop, Config
  memory/               -- 6-Layer Memory (SQLite + ChromaDB)
  orchestrator/         -- Task routing, Composer, Cache, Resilience
  research/             -- arXiv + GitHub research pipeline
  training/             -- Model build pipeline (5 phases)
  cli/                  -- Terminal UI
  gateway/              -- API Gateway
  cognition/            -- Drives, Goals
  network_manager/      -- Multi-node network management
  scripts/              -- Deploy, Monitoring, Utilities
  docs/                 -- Documentation, plans, roundtable protocols
```

## Compute Network

Way2AGI is designed to run across multiple nodes. Example setup:

| Node Role | Port | Description |
|-----------|------|-------------|
| Inference Node | 8050 | Primary controller, memory, always-on inference |
| Compute Node | 8100 | Heavy compute, model training (GPU required) |
| NPU Node | 8150 | Orchestration server, lightweight agents |
| Mobile Node | 8200 | Lite inference, verification |

Configure your nodes in `.env` and `cli/config.py`.

## Core Components

- **MicroOrchestrator:** Bid-based model routing across 20+ models
- **Research Pipeline:** arXiv + GitHub scraping, LLM analysis, auto-TODO creation
- **6-Layer Memory System:** SQLite-based persistent memory with entities, relations, goals, rules
- **Training Pipeline:** 5 phases (Abliterate, Distill, SFT, Publish, GGUF)
- **Speculative Decoding:** Large + small model draft/verify for 2x speedup
- **Cloud API Integration:** Groq, OpenRouter, Ollama Cloud, OpenAI, xAI, Gemini
- **Persistent Roundtable:** Multi-model discussion with 5 agents and 4-level scaling
- **Autonomous Cronjobs:** GoalGuard, Research, Implementation, Training, Self-Observation

## Setup

```bash
git clone https://github.com/YOUR_GITHUB_USER/Way2AGI.git
cd Way2AGI
cp .env.example .env
# Edit .env with your configuration (API keys, node IPs, etc.)
pip install -r requirements.txt  # or: pnpm install (for gateway/cli)
```

### Configuration

1. Copy `.env.example` to `.env` and fill in your values
2. Configure node IPs in `cli/config.py`
3. Set up SSH access between nodes
4. Install Ollama on inference nodes

## Cronjobs

| Time | Script | Purpose |
|------|--------|---------|
| 07:00 | research.py | Scrape arXiv + GitHub for new research |
| 08/14/20 | goalguard.py | Check rules, process TODOs |
| 12:00 | roundtable.py | Distribute research findings to all models |
| 16:00 | implement.py | Implement TODOs as code |
| 06:00 | daily_report.py | Generate daily report |
| Every 30min | self_observe.py | Self-monitoring and error detection |

## Training Pipeline

5-phase pipeline for fine-tuning models (requires GPU node):

1. **PRISM Abliteration** — Remove refusal mechanisms
2. **Knowledge Distillation** — Collect traces from large models
3. **SFT Training** — LoRA fine-tuning on abliterated model
4. **Publish** — Model card + push to HuggingFace
5. **GGUF** — Convert for llama.cpp/Ollama deployment

## License

MIT License (see LICENSE file)

## Contributing

This project is in active development. Issues and PRs welcome.
