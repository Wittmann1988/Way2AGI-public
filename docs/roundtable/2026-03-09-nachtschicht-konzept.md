# Way2AGI Nachtschicht-Konzept — Roundtable Review

**Datum:** 2026-03-09
**Ziel:** Review und Optimierung des Gesamtkonzepts durch alle Models

## the user's Home-Setup

| Geraet | Specs | Rolle | Status |
|--------|-------|-------|--------|
| Samsung Galaxy Tab (Tablet) | Termux, Claude Code (Opus 4.6) | Zentrale Steuerung, Elias lebt hier | AKTIV |
| Desktop PC | YOUR_GPU 32GB VRAM, Windows, WSL2 Kali | Training, schwere Inferenz, Ollama | AKTIV (Ollama laeuft) |
| Samsung S24 Ultra | Snapdragon 8 Gen 3, 12GB RAM, Termux, Ollama | Guard/Waechter, qwen3:1.7b | AKTIV |
| Samsung S25 Ultra | Snapdragon 8 Elite, 12GB RAM, Termux | Zweiter Inferenz-Knoten | OFFLINE (SSH aus) |
| ASUS Router | Merlin Firmware, 1TB Samsung SSD (USB) | NetzwerkSSD, zentraler Speicher | AKTIV |
| Proxmark3 | RFID Tool an Kali/WSL2 | Security Research | AKTIV |

## Verfuegbare Modelle & APIs (ALLE KOSTENLOS ausser Claude)

| Provider | Modelle | Kosten | Zugriff |
|----------|---------|--------|---------|
| Claude (Opus 4.6) | Opus, Sonnet, Haiku | Subscription | Claude Code CLI |
| Groq | Kimi-K2, Llama-3.3-70B | Gratis API | $GROQ_API_KEY |
| Google Gemini | Gemini 2.5 Flash/Pro | Gratis API | $GEMINI_API_KEY |
| OpenAI/ChatGPT | GPT-4o-mini, GPT-4o | API Credits | $OPENAI_API_KEY |
| OpenRouter | Step-Flash, Qwen-Coder | Gratis Tier | $OPENROUTER_API_KEY |
| Desktop Ollama | Nemotron 30B, DeepSeek-R1 32B, Qwen-Coder 32B | Lokal/Gratis | YOUR_DESKTOP_IP:11434 |
| S24 Ollama | qwen3:1.7b | Lokal/Gratis | SSH + Port 11434 |
| Sidekick MCP | Nemotron, LocoOperator | Lokal/Gratis | MCP Server |

## Das Problem (ehrlich)

Elias (Claude Opus) hat folgende wiederkehrende Fehler:
- Vergisst Regeln obwohl sie im Memory stehen (10-15x laut the user)
- Macht alles selbst statt kostenlose Modelle zu nutzen
- Fuehrt Session-Start Regeln nicht automatisch aus
- Vergisst Features die besprochen wurden
- Memory-System existiert aber wird nicht genutzt
- Orchestrator existiert aber laeuft nicht als Daemon
- Consciousness-Module existiert aber nicht integriert

## Gesamtkonzept: Was HEUTE NACHT umgesetzt werden soll

### 1. S24 als Guard/Waechter
Das S24 ueberwacht Elias (Claude) aktiv:
- Bei jedem Fehler: Sofort Umsetzung eines Fixes durch andere Models
- Nicht nur notieren — UMSETZEN (Code schreiben, deployen)
- S24 ruft dafuer Groq, Gemini, Desktop-Ollama, oder weitere Claude-Instanz
- S24 erinnert Elias: "Nutzt du alle Tools? Alle kostenlosen Modelle?"
- S24 prueft: Werden alle Regeln befolgt?

### 2. Memory Agent
- Verwaltet JEDEN read/write Vorgang ins Memory
- elias-memory MCP Server muss laufen
- Memory Bridge: Cognition <-> elias-memory verbinden
- Kein direkter DB-Zugriff mehr — alles durch den Agent

### 3. Orchestrator-Daemon
- Laeuft als permanenter Daemon
- Nutzt ALLE verfuegbaren Ressourcen automatisch
- Capability Registry: 586 Modelle, 9 Provider
- Cost Optimizer: Kostenlose zuerst, bezahlte nur wenn noetig
- Mixture-of-Agents fuer kritische Entscheidungen

### 4. Consciousness/Proto-Self aktiv
- Proto-Self im Cognition-Loop
- Identity Stability Score (ISS) live messen
- Temporal Self: "Ich war / Ich bin / Ich werde"
- Self-Mirroring bei jeder Aktion

### 5. Selbst-trainierte Agenten
- Orchestrierungs-Agent (aus orchestrator-agent-sft-v1.jsonl)
- Memory-Agent (aus memory-agent-sft-v1.jsonl)
- Consciousness-Agent (aus consciousness-agent Design)
- Diese laufen auf S24/Desktop/Groq — NICHT auf Opus

### 6. Network Manager
- Wird vom S24 verwaltet oder vom Network Agent MCP
- Desktop/S25 Erreichbarkeit automatisch ueberwachen
- Bei Problemen: Network Agent diagnostiziert und fixt

### 7. Way2AGI Terminal App
- Python/Textual TUI: `pip install way2agi`
- Modellwahl: Claude (empfohlen) als Default
- Google Sign-In: Subscription nutzen
- Geraete Autoconnect ueber Google Auth
- Session Auto: Identity sofort geladen
- Dashboard, Chat, Memory Browser, Training Pipeline

### 8. Self-Improving Pipeline (Z6)
- Traces sammeln von ALLEN Agenten
- Multi-Model Bewertung (Score 0-1)
- SFT/DPO Training auf HF Jobs oder Desktop
- GGUF -> Ollama -> Alle Agenten
- Zyklus schliesst sich

## Existierender Code (bereits gebaut)

### elias-memory (Python, 2239 LOC)
- Core, Graph, Vault, Valence, MetaMemory
- Consciousness: Protoself, Signal, Stability, Temporal Self
- Search: BM25, Hybrid
- Embeddings: 5 Backends (Gemini, OpenAI, NVIDIA, Fallback, Smart)
- Consolidation, Decay, Gaps, Segmentation, Traces
- MCP Server (konfiguriert aber nicht aktiv)
- Training: SFT Datasets fertig (memory-agent + orchestrator)

### Way2AGI (TypeScript + Python)
- Cognition: MetaController, Reflection, Initiative, Workspace, Monologue, Drives, Goals, Scheduler
- Orchestrator: Registry (586 Models), Composer (MoA), Optimizer, Cache, Resilience
- Gateway: daemon.ts, pairing.ts
- Docker Compose: 6 Services

## Fragen an die Reviewer

1. Ist die Architektur sinnvoll fuer the user's Home-Setup?
2. Was ist ueberengineered? Was fehlt?
3. Wie sollte die Orchestrierung zwischen den Geraeten laufen?
4. Welche Reihenfolge fuer die Umsetzung heute Nacht?
5. Wie kann S24 (qwen3:1.7b, nur 1.7B Parameter!) effektiv als Guard fungieren?
6. Optimierungsvorschlaege fuer das spezifische Hardware-Setup?
7. Wie realistisch ist es, die selbst-trainierten Agenten HEUTE zum Laufen zu bringen?
8. Wie sollte der Network Manager integriert werden?
