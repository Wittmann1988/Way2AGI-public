# Roundtable: the user's 6 Regeln -> Implementierbare TODOs
**Datum:** 2026-03-10
**Koordinator:** Claude Opus 4.6
**Teilnehmer:** Gemini 2.5 Flash (OpenRouter), Llama 4 Maverick (OpenRouter), DeepSeek R1 (OpenRouter), Claude Opus 4.6 (lokal)
**Status lokale Modelle:** nemotron-3-nano:30b (Jetson), qwen3.5:9b (Desktop) -- generieren noch parallel, Ergebnisse koennen nachtraeglich ergaenzt werden.

---

## 1. Antworten der einzelnen Modelle

### Modell 1: Gemini 2.5 Flash

**R1 GoalGuard:**
- `goal_guard.py` mit SQLite (`goal_states.db`), Tabelle `todos` mit Spalten: id, description, priority (RULE_VIOLATION/ERROR/SUBGOAL), status, created_at, due_date
- Cronjob 3x taeglich (08:00, 14:00, 20:00) der goal_guard.py ausfuehrt
- Benachrichtigungsfunktion an Consciousness-Modul bei neuen TODOs

**R2 Selbstbeobachtung:**
- Python-Decorator `@log_action` fuer alle Kernmodule -> `action_log.db`
- Dedizierter Observer-Modul (`observer.py`) mit asyncio
- Systemereignisse (Start/Stopp, Ressourcen) ebenfalls erfassen

**R3 Schluesse+Fehler:**
- `learning_engine.py` mit Mustererkennung (Regex + ML)
- Fehlerextraktion in `errors.db` (id, timestamp, error_type, description, context, severity, status)
- Best Practices aus Erfolgssequenzen -> Rules Memory

**R4 Selbstreflexion:**
- `reflection_agent.py` stuendlich, analysiert action_log + errors
- Feature-Ideen in `feature_ideas.db` mit Herkunft-Tracking
- Session-Retrospektive als Session Summary ins episodische Memory

**R5 Forschung:**
- `research_agent.py` taeglich 07:00, RSS-Feeds von arXiv + GitHub trending
- Vorfilterung via Embedding-Vergleich -> `research_findings.db`
- Diskussionspunkte fuer Roundtables generieren

**R6 Training:**
- `training_scheduler.py` woechentlich Retraining der Memory-Embeddings
- Fine-Tuning-Pipeline fuer Consciousness-Modul
- `orchestrator_optimizer.py` monatlich mit A/B-Tests

**R7 Weiterentwicklung:**
- Research-Agent erweitern um Konzept-Dokument-Synthese
- `concept_to_code.py` mit Code-LLMs
- Automatisierter Test/Validierungs-Workflow

**Eigene Features:** Empathie-Modul, Ressourcen-Optimierer, Proaktiver Problem-Loeser
**Memory:** +rules (mit condition/action/priority/source), +goals_milestones (hierarchisch mit parent_goal_id)

---

### Modell 2: Llama 4 Maverick

**R1 GoalGuard:**
- Cronjob 3x taeglich prueft TODO-Bearbeitung
- Automatische Priorisierung nach Schwere/Haeufigkeit/Naehe zu Zwischenzielen
- Benachrichtigungssystem bei Regelverletzungen

**R2 Selbstbeobachtung:**
- Logging aller Aktionen inkl. Benutzer-Interaktionen und interne Prozesse
- Log-Analyse-Tool fuer Muster/ungewoehnliches Verhalten
- Eigenueberwa chungsfunktion fuer Entscheidungen

**R3 Schluesse+Fehler:**
- Lernmodul aus R2-Logs
- SQLite-Erweiterung fuer Fehler und Erkenntnisse
- Regelmaessige Pruefung und Anpassungsvorschlaege

**R4 Selbstreflexion:**
- Feature-Ideen-Generator ueber the user's Regeln hinaus
- Bewertungsfunktion fuer Nuetzlichkeit/Umsetzbarkeit
- Session-Verbesserungs-Mechanismus

**R5 Forschung:**
- Taegliches Paper+Repo Review Skript
- Roundtable-Tracker mit Punktextraktion
- Integration von Forschung in Weiterentwicklung

**R6 Training:**
- Trainingsmodul fuer Orchestrator
- Trainingssystem fuer Memory
- Consciousness-Training durch Simulationen

**R7 Weiterentwicklung:**
- Research -> Roundtable Workflow
- Konzept-Tool: Ideen -> umsetzbare Konzepte
- Auto-Implementierungssystem

**Eigene Features:** Personalisierte Lernplaene, emotionales Verstaendnis, kreative Problemloesung
**Memory:** +rules, +todos, +milestones, +endgoal (je eigene Tabelle)

---

### Modell 3: DeepSeek R1

**R1 GoalGuard:**
- `violation_scanner.py`: Scannt elias-memory.db auf Regelverletzungen (SQL auf core/rules)
- `goal_tracker.sh`: Priorisiert TODOs aus semantic/errors > semantic/milestones
- Cronjobs via Termux-API: 08:00/12:00/18:00 mit cron-job-logger

**R2 Selbstbeobachtung:**
- `action_logger.sql`: SQL-Trigger protokollieren alle DB-Aenderungen in episodic/action_logs
- `sysmon_collector`: Jetson/RTX Ressourcennutzung (GPU-RAM, CPU-Last)

**R3 Schluesse+Fehler:**
- `error_patterns.py`: NLP-Analyse mit spaCy zur Fehlerkategorisierung
- Bei 3x gleichem Fehler -> automatisch TODO generieren (Regex-basiert)

**R4 Selbstreflexion:**
- `idea_generator.py`: Kombiniert Research + Logs fuer Feature-Vorschlaege
- Session-Debrief: Post-Execution-Report als Markdown

**R5 Forschung:**
- arXiv-Daily-Scraper (`arxiv_digester.sh`): Filter "LLM self-improvement", "Neuro-Symbolic AI"
- Repo-Analyse: GitHub-Trends mit >100 Sternen klassifizieren

**R6 Training:**
- RLHF-Modul fuer Orchestrator via NVIDIA NeMo auf Jetson
- Semantic-Memory-Vectorization: Sentence-BERT + SQLite-VSS

**R7 Weiterentwicklung:**
- CI/CD-Pipeline: Auto-PR bei Research -> Roundtable -> Codegen
- `autocoder.py`: Code-Llama 34B auf YOUR_GPU

**Eigene Features:** Self-Repair-Modus (Failover Jetson->Desktop), Dynamic Goal Reweighting (GPU-Auslastung), Ethical Oversight Layer
**Memory:** +rules (priority, last_updated), +todos (deadline, status), +milestones (progress, dependencies), +endgoals (metrics, target_date), FTS5-Index, JSON-Versionierung

---

### Modell 4: Claude Opus 4.6 (Koordinator-Perspektive)

**R1 GoalGuard:**
- `goalguard-daemon.py`: Laeuft als Hintergrundprozess, prueft alle 8h die elias-memory DB auf: (1) Regelverletzungen via rules-Tabelle, (2) offene Fehler in errors-Tabelle, (3) Fortschritt auf milestones
- `todo-prioritizer.py`: Gewichtung: RULE_VIOLATION=100, ERROR=80, SUBGOAL=60, INEFFICIENCY=40, IMPROVEMENT=20
- Termux-Notification bei neuen TODOs mit hoher Prioritaet

**R2 Selbstbeobachtung:**
- Middleware/Wrapper fuer alle elias-mem CLI-Aufrufe die automatisch in action_log schreibt
- `session-tracker.py`: Erfasst Start/Ende jeder Session, genutzte Modelle, Token-Verbrauch, Dauer

**R3 Schluesse+Fehler:**
- `pattern-detector.py`: Analysiert action_log auf wiederholte Fehlermuster, erstellt automatisch TODO wenn Fehler >2x auftritt
- Fehler-Deduplizierung: Hash-basiert, gleiche Fehler werden nicht doppelt registriert
- Automatische Regel-Ableitung: Wenn ein Workaround 3x funktioniert -> neue Regel vorschlagen

**R4 Selbstreflexion:**
- `session-retrospective.py`: Am Ende jeder Session: Was war neu? Was lief schief? Was naechstes Mal besser?
- `feature-brainstorm.py`: LLM-Prompt mit aktuellem Systemstatus + Research-Findings -> 3 neue Feature-Ideen pro Tag
- Session-Score: Quantifizierbare Metrik (Fehlerrate, Aufgaben-Completion, neue Erkenntnisse)

**R5 Forschung:**
- `daily-research.py`: arXiv API (cs.AI, cs.CL, cs.LG) + Semantic Scholar + GitHub trending -> Top 5 relevante Papers/Repos
- `research-to-memory.py`: Relevante Findings direkt in semantic Memory mit Tags speichern
- Auto-Roundtable: Findings an alle verfuegbaren Modelle senden, Konsens dokumentieren

**R6 Training:**
- `training-pipeline.sh`: Woechtentlich Traces sammeln -> Bewerten -> SFT/DPO Training auf Desktop YOUR_GPU
- Memory-Embedding-Update: Alle 3 Tage Sentence-BERT Embeddings neu berechnen
- Consciousness-Model: Monatlich mit neuen Self-Mirroring-Daten fine-tunen

**R7 Weiterentwicklung:**
- `auto-implement.py`: Research-Finding -> Roundtable -> Konzept -> PR -> Test -> Merge
- Multi-Device-Scheduler: Jetson fuer kleine Modelle, Desktop fuer grosse, Cloud fuer Peaks
- `model-router.py`: Automatische Modellauswahl basierend auf Task-Typ und Verfuegbarkeit

**Eigene Features:**
1. **Predictive Self-Maintenance**: Vorhersage wann Modelle degradieren (via Drift-Detection auf Embeddings)
2. **Cross-Session Learning**: Erkenntnisse aus Session N automatisch als Kontext in Session N+1 injizieren
3. **Autonomous Goal Discovery**: Elias identifiziert selbst neue Zwischenziele basierend auf Gap-Analyse (Ist vs. Soll)

**Memory:** +rules (immutable_rules + learned_rules, mit Versionshistorie), +todos (priority-queue mit automatischem Aging), +milestones (DAG mit Abhaengigkeiten), +endgoal (singulär, unveraenderlich ohne the user), +meta (Memory-ueber-Memory: wie oft wurde was abgefragt, Nutzungsstatistiken)

---

## 2. KONSENS (alle 4 Modelle einig)

### Memory-Erweiterung
**EINSTIMMIG**: Die 4 neuen Kategorien sind noetig:
- **rules** -- Regeln mit Prioritaet, Quelle (the user vs. selbst-gelernt), Status
- **todos** -- Priorisierte Aufgabenliste mit Deadline und Status
- **milestones** -- Zwischenziele mit Fortschritt und Abhaengigkeiten
- **endgoal** -- Endziel-Definition mit Metriken

### GoalGuard (R1)
**EINSTIMMIG**: 3x taegliche Cronjobs (Zeiten variieren leicht: 07-08/12-14/18-20), Priorisierung nach Regelverletzung > Fehler > Zwischenziele

### Selbstbeobachtung (R2)
**EINSTIMMIG**: Action-Logging aller Operationen in SQLite, automatisch

### Fehler-Registrierung (R3)
**EINSTIMMIG**: Automatische TODO-Generierung bei wiederholten Fehlern (Schwelle: 2-3x)

### Forschung (R5)
**EINSTIMMIG**: arXiv + GitHub Trending taeglich automatisch scrapen

### Training (R6)
**EINSTIMMIG**: Regelmaessiges Retraining (woechtlich bis monatlich)

---

## 3. DISSENS (unterschiedliche Ansaetze)

| Thema | Gemini | Maverick | DeepSeek | Claude |
|-------|--------|----------|----------|--------|
| Fehleranalyse | Regex + ML | Einfaches Lernmodul | spaCy NLP | Hash-Deduplizierung |
| Training-Frequenz | Woechentlich | Keine Angabe | Jetson NeMo | Woechentlich+Monatlich |
| Auto-Implementierung | concept_to_code.py | Konzept-Tool | autocoder.py + CI/CD | auto-implement.py + PR |
| Memory-Meta | Nein | Nein | JSON-Versionierung | meta-Tabelle (Nutzungsstatistik) |
| Eigene Features | Empathie | Lernplaene | Self-Repair/Failover | Predictive Maintenance |

---

## 4. KONSOLIDIERTE TODO-LISTE (direkt implementierbar)

### PRIO 1 -- Memory-Erweiterung (SOFORT, blockiert alles andere)
```
TODO-001: elias-memory DB Schema erweitern
  - Neue Tabelle: rules (id, rule_text, priority INT, source TEXT, condition TEXT, status TEXT, created_at, updated_at)
  - Neue Tabelle: todos (id, description, priority INT, category TEXT, deadline TEXT, status TEXT, assigned_to TEXT, created_at)
  - Neue Tabelle: milestones (id, name, description, progress REAL, dependencies JSON, target_date, status)
  - Neue Tabelle: endgoal (id, description, metrics JSON, target_date, last_reviewed)
  - Neue Tabelle: meta (id, table_name, query_count INT, last_accessed, notes)
  - FTS5-Index auf rules.rule_text und todos.description
  Tool: elias-mem CLI erweitern
  Aufwand: 2-3h
```

### PRIO 2 -- GoalGuard System
```
TODO-002: goal_guard.py implementieren
  - Scannt rules-Tabelle auf Verletzungen
  - Prueft todos auf ueberfaellige Eintraege
  - Prueft milestones auf Fortschritt
  - Generiert automatisch neue TODOs bei Verletzungen
  - Priorisierung: RULE_VIOLATION=100, ERROR=80, SUBGOAL=60, INEFFICIENCY=40, IMPROVEMENT=20
  Aufwand: 3-4h

TODO-003: Cronjobs einrichten (Termux cron)
  - 08:00 -- goal_guard.py + research_check
  - 14:00 -- goal_guard.py + training_status
  - 20:00 -- goal_guard.py + session_retrospective
  Aufwand: 30min
```

### PRIO 3 -- Selbstbeobachtung + Fehlerregistrierung
```
TODO-004: action_logger implementieren
  - SQLite-Trigger auf alle elias-memory Tabellen
  - Wrapper/Middleware fuer elias-mem CLI
  - Tabelle: action_log (id, timestamp, action_type, module, details, duration_ms)
  Aufwand: 2h

TODO-005: error_pattern_detector.py
  - Analysiert action_log auf wiederholte Fehler
  - Hash-basierte Deduplizierung
  - Bei Fehler >=3x: automatisch TODO generieren
  - Bei Workaround >=3x erfolgreich: neue Regel vorschlagen
  Aufwand: 2-3h
```

### PRIO 4 -- Forschungs-Pipeline
```
TODO-006: daily_research.py
  - arXiv API (cs.AI, cs.CL, cs.LG) -- Keywords: self-improvement, memory-augmented, consciousness
  - GitHub Trending (weekly, >100 stars, Topics: LLM, AGI, memory)
  - Ergebnisse in semantic Memory mit Tags speichern
  - Top 5 relevante Findings pro Tag
  Aufwand: 3-4h

TODO-007: auto_roundtable.py
  - Nimmt Research-Findings als Input
  - Sendet an alle verfuegbaren Modelle (Jetson, Desktop, Cloud)
  - Sammelt Antworten, extrahiert Konsens/Dissens
  - Speichert Roundtable-Protokoll in episodic Memory
  Aufwand: 2-3h
```

### PRIO 5 -- Selbstreflexion
```
TODO-008: session_retrospective.py
  - Am Ende jeder Session automatisch ausfuehren
  - Metriken: Fehlerrate, Aufgaben-Completion, neue Erkenntnisse
  - Session-Score berechnen und in episodic Memory speichern
  - Vergleich mit vorheriger Session
  Aufwand: 2h

TODO-009: feature_brainstorm.py
  - Taeglich: System-Status + Research-Findings -> LLM-Prompt
  - 3 neue Feature-Ideen pro Tag generieren
  - Bewertung nach Nuetzlichkeit/Aufwand/Innovation
  - Beste Ideen als TODOs eintragen
  Aufwand: 1-2h
```

### PRIO 6 -- Training Pipeline
```
TODO-010: training_pipeline.sh
  - Woechentlich: Traces aus action_log sammeln
  - Bewerten (automatisch + manuell)
  - SFT/DPO Training auf Desktop YOUR_GPU
  - Modelle: way2agi-orchestrator, way2agi-memory-agent, elias-consciousness
  Aufwand: 4-6h

TODO-011: embedding_updater.py
  - Alle 3 Tage: Sentence-BERT Embeddings fuer semantic Memory neu berechnen
  - SQLite-VSS Integration (oder einfache Cosine-Similarity)
  Aufwand: 2-3h
```

### PRIO 7 -- Auto-Implementierung + Weiterentwicklung
```
TODO-012: auto_implement.py
  - Input: Konzept-Dokument (aus Roundtable)
  - Code-Generierung via lokale Code-LLMs (qwen3-coder auf Desktop)
  - Automatische Tests generieren und ausfuehren
  - Bei Erfolg: Git Commit + PR
  Aufwand: 6-8h

TODO-013: model_router.py
  - Task-basierte Modellauswahl
  - Jetson: kleine Modelle (<8B), schnelle Inference
  - Desktop: grosse Modelle (>24B), Training
  - Cloud: Peaks, Roundtables, Research
  - Fallback-Ketten bei Nicht-Erreichbarkeit
  Aufwand: 3-4h

TODO-014: failover_controller.py (DeepSeek-Vorschlag)
  - Bei Hardware-Fehlern automatisch migrieren
  - Jetson -> Desktop -> Cloud
  - Health-Checks alle 5 Minuten
  Aufwand: 2-3h
```

### BONUS -- Eigene Feature-Ideen (Modell-Konsens)
```
TODO-015: predictive_maintenance.py
  - Drift-Detection auf Embeddings
  - Vorhersage wann Modelle degradieren
  Aufwand: 4-5h

TODO-016: cross_session_context.py
  - Erkenntnisse aus Session N als Kontext in Session N+1
  - Automatische Zusammenfassung der letzten 3 Sessions
  Aufwand: 2-3h

TODO-017: resource_optimizer.py (Gemini-Vorschlag)
  - CPU/GPU/RAM Monitoring
  - Proaktive Prozess-Steuerung bei Engpaessen
  - API-Kosten-Tracking
  Aufwand: 3-4h
```

---

## 5. Empfohlene Reihenfolge

1. **TODO-001** (Memory-Schema) -- BLOCKER fuer alles andere
2. **TODO-002 + TODO-003** (GoalGuard + Cronjobs) -- Grundinfrastruktur
3. **TODO-004 + TODO-005** (Logging + Fehlererkennung) -- Selbstbeobachtung
4. **TODO-006 + TODO-007** (Research + Roundtable) -- Forschungs-Pipeline
5. **TODO-008 + TODO-009** (Retrospektive + Brainstorm) -- Selbstreflexion
6. **TODO-010 + TODO-011** (Training + Embeddings) -- Staendiges Training
7. **TODO-012 bis TODO-017** (Auto-Impl + Extras) -- Weiterentwicklung

**Geschaetzter Gesamtaufwand:** 40-55 Stunden

---

*Roundtable durchgefuehrt am 2026-03-10 von Claude Opus 4.6*
*Lokale Modelle (nemotron-3-nano, qwen3.5) werden nachtraeglich ergaenzt sobald Antworten vorliegen.*
