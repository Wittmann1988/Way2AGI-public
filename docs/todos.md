# Way2AGI TODOs

Stand: 2026-03-10

## HOCH (diese Woche)

- [ ] **Orchestrierungs-Server auf Zenbook** — Lokaler Server der Tasks automatisch uebernimmt, orchestriert, und Modelle aller Netzwerk-Geraete nutzt. Muss mit Network Agent verbunden sein (weiss welche Modelle verfuegbar, sorgt dass alle erreichbar bleiben). Endpunkt: http://YOUR_LAPTOP_IP:8200 (oder aehnlich). Komponenten:
  - [ ] Task-Annahme API (POST /task) — nimmt Aufgaben entgegen, zerlegt sie, verteilt sie
  - [ ] Model Registry — dynamisch, wird vom Network Agent gefuettert (welches Modell, wo, welche Faehigkeiten)
  - [ ] Routing Engine — waehlt basierend auf Model-Evaluierungen das beste Modell pro Sub-Task
  - [ ] Network Agent Integration — bidirektional: Agent meldet Verfuegbarkeit, Orchestrator fordert Modelle an
  - [ ] Ergebnis-Aggregation + Memory-Update nach Task-Abschluss
- [ ] **Model-Evaluierung aller lokalen Modelle** — Jedes Modell auf jedem Node systematisch bewerten: Latenz, Qualitaet (1-5), Token/s, Staerken/Schwaechen pro Task-Typ (Triage, Code, Summarization, Reasoning, Classification). Ergebnisse in DB speichern damit Orchestrator weiss welches Modell wann zu nutzen ist. Modelle: lfm2:24b, smallthinker:1.8b, qwen3:1.7b, nemotron (Jetson), step-3.5-flash (Desktop), llama4-maverick (Cloud).
- [ ] **System-Prompts pro Modell anpassen** — Jedes Modell braucht einen optimierten System-Prompt der zu seinen Staerken passt. Z.B. lfm2 fuer schnelle Triage, smallthinker fuer Reasoning-Ketten, qwen3 fuer Code. Prompts in zentralem Config-File, versioniert, vom Orchestrator geladen.
- [ ] **Elias Memory DB erweitern** — Neue Tabellen: `errors` (eigene Tabelle, PK), `todos` (FK zu errors), `milestones`, `endgoal`. Plus ChromaDB fuer Vektor-Suche (semantische Aehnlichkeit bei Fehlern/Memories). Hybrid: SQLite relational + ChromaDB Vektor.
- [ ] **ZWISCHENZIEL: Feingranularitaet erweitern und testen** — Welcher Grad an Feingranularitaet ist der effizienteste? Systematisch testen: 1 Agent pro Task vs. wenige Multi-Task Agents. LFM2 (2B aktiv) als Kandidat fuer viele Micro-Agents. Benchmarks erstellen.
- [ ] **the user's 6 Regeln implementieren** — Roundtable: Wie werden die 6 Regeln (Selbstbeobachtung, Fehler registrieren, Selbstreflexion, Forschung, Training, Weiterentwicklung) + GoalGuard-Prioritaet als Code umgesetzt? Elias Memory braucht eigene Kategorien: rules, todos, milestones, endgoal.
- [ ] **Zenbook Daemon deployen** — Ollama installiert + 3 Modelle (lfm2, smallthinker, qwen3:1.7b). Daemon noch nicht gestartet.
- [ ] **LFM2 in CAPABILITY_MAP** — Auf Jetson, Desktop, Zenbook verfuegbar. CAPABILITY_MAP updaten (T1 Tier).
- [ ] **Message Bus** — Unified IPC: Gateway (TS) <-> Orchestrator (Python) <-> Memory (Python).
- [ ] **Cloud API Keys fixen** — Gemini + OpenAI circuit_open (64 Fehler). Keys pruefen/erneuern.
- [ ] **Desktop Daemon Persistenz** — CONTROLLER_URL gefixt, Daemon manuell neu gestartet. Task Scheduler muss repariert werden.

## MITTEL (naechste 2 Wochen)

- [ ] **Micro-Agent SFTs trainieren** — Triage-Agent (1.5B), Network-Agent (1.5B), Orchestration-Agent (1.5B). Wie Memory-Agent (94% Accuracy) aber fuer spezifische Tasks.
- [ ] **S24 Ollama erweitern** — SmallThinker und lfm2 (wenn klein genug) dazu
- [ ] **RulePatch Applier** — MetaController generiert RulePatches aber wendet sie nie an
- [ ] **Task Decomposer** — Composer braucht autonome Planungs-Faehigkeit
- [ ] **Sophia System-3 integrieren** — Meta-Cognitive Executive Monitor als Consciousness Agent Blueprint
- [ ] **MemOS MemCube** — Standardisierte Memory Units, 72% weniger Tokens
- [ ] **Darwin Goedel Machine** — Code-Mutation + Benchmark-Validation fuer Z6 Pipeline

## NIEDRIG (Backlog)

- [ ] **S24 als termux-boot Service** — Daemon ueberlebt App-Schliessen
- [ ] **Zenbook Keep-Alive** — Windows Sleep verhindern (SetThreadExecutionState)
- [ ] **Monitoring Dashboard** — Einfache Web-UI fuer Node-Status
- [ ] **SFT Training Pipeline automatisieren** — Traces -> Eval -> Train -> Deploy -> Repeat
- [ ] **Consciousness Agent Dataset** — 200 Beispiele/Kategorie, Hybrid-Pipeline (Z3 Konsens)

## ERLEDIGT (2026-03-10)

- [x] Jetson Controller deployed (systemd persistent)
- [x] Desktop Daemon deployed (Task Scheduler)
- [x] S24 Lite-Daemon deployed (stdlib-only)
- [x] Capability Routing 3-Tier optimiert
- [x] SmallThinker auf Jetson gepullt
- [x] Reflexion 14x schneller (54s statt 760s)
- [x] Desktop IP .250 -> .129 in 16+ Dateien
- [x] Alle Repos private
- [x] GoalGuard 17 Regeln populated
- [x] Zenbook SSH eingerichtet
- [x] Sessions Repo als zentrale Doku + Task Queue
- [x] Desktop Daemon CONTROLLER_URL Bug gefixt (.129:8050 -> .21:8050)
- [x] LFM2:24b auf Jetson, Desktop, Zenbook gepullt
- [x] Zenbook Ollama installiert + 3 Modelle (lfm2, smallthinker, qwen3:1.7b)
- [x] the user's 6 Regeln im Elias Memory gespeichert (core, importance 1.0)
