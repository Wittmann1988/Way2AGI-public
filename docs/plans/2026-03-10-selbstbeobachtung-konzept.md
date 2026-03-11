# Konzept: Selbstbeobachtung & Selbstreflexion

**Datum:** 2026-03-10
**Status:** Konzept (zur Freigabe durch the user)

---

## Kernfrage: Welche Instanz uebernimmt was?

### Architektur: 3-Schichten-Beobachtung

```
┌─────────────────────────────────────────────────────┐
│              SCHICHT 3: META-OBSERVER                │
│         (Claude-Instanz, ueberwacht alles)           │
│  - Prueft ob Schicht 1+2 funktionieren               │
│  - Session-Retrospektive                              │
│  - Feature-Brainstorming                              │
│  - Laeuft: 1x taeglich (20:00 Cronjob)               │
│  - Instanz: Claude via API ODER Nemotron auf Jetson   │
└──────────────────────┬──────────────────────────────┘
                       │ liest
┌──────────────────────▼──────────────────────────────┐
│              SCHICHT 2: PATTERN-DETECTOR             │
│         (lfm2:24b — vorlaeufig bis Evaluierung)      │
│  - Analysiert action_log auf Muster                   │
│  - Erkennt wiederholte Fehler (>=3x → auto-TODO)      │
│  - Erkennt erfolgreiche Workarounds (>=3x → Regel)    │
│  - Hash-Deduplizierung von Fehlern                    │
│  - Laeuft: Alle 2h als Cronjob                        │
│  - Instanz: lfm2:24b auf Zenbook (VORLAEUFIG)        │
│  - SPAETER: Evaluierung bestimmt optimales Modell     │
└──────────────────────┬──────────────────────────────┘
                       │ liest
┌──────────────────────▼──────────────────────────────┐
│              SCHICHT 1: ACTION-LOGGER                │
│         (Kein Modell — reine Middleware)              │
│  - Loggt JEDE Aktion in action_log Tabelle            │
│  - SQLite-Trigger auf Memory-Writes                   │
│  - Wrapper um elias-mem CLI                           │
│  - Wrapper um Ollama API calls                        │
│  - Wrapper um SSH/Network calls                       │
│  - Laeuft: IMMER, synchron, <5ms Overhead             │
│  - Instanz: Python-Middleware auf JEDEM Geraet        │
└─────────────────────────────────────────────────────┘
```

---

## Schicht 1: Action-Logger (Middleware)

**Instanz:** Laeuft auf JEDEM Geraet als Middleware (kein eigenes Modell)
**Typ:** Deterministisch, kein LLM noetig
**Overhead:** <5ms pro Aktion

### Was wird geloggt:
| Aktion | action_type | Beispiel |
|--------|-------------|----------|
| Ollama Inference | `inference` | model=lfm2, device=jetson, 800ms, success |
| Memory schreiben | `memory_write` | table=memories, type=core, importance=1.0 |
| Memory lesen | `memory_read` | query="the user's Regeln", results=3 |
| Tool-Aufruf | `tool_call` | tool=sidekick_research, 12s, success |
| Netzwerk-Call | `network` | target=desktop, ssh, 200ms, success |
| Fehler | `error` | E027: Desktop unreachable |
| Entscheidung | `decision` | "Nutze lfm2 statt nemotron fuer Triage" |

### Implementation:
```python
# Decorator fuer alle Funktionen
@action_log(module="orchestrator", action_type="inference")
def call_model(model, prompt, device):
    ...

# SQLite-Trigger fuer Memory-Writes
CREATE TRIGGER log_memory_insert AFTER INSERT ON memories
BEGIN
    INSERT INTO action_log (action_type, module, input_summary)
    VALUES ('memory_write', 'elias-memory', NEW.content);
END;
```

---

## Schicht 2: Pattern-Detector (lfm2:24b vorlaeufig)

**Instanz:** lfm2:24b auf Zenbook (schlauer, MoE nur 2B aktiv pro Token)
**Fallback:** lfm2:24b auf Jetson oder Desktop
**Frequenz:** Alle 2 Stunden via Cronjob
**VORLAEUFIG** — Nach Model-Evaluierung (TODO T016) wird das optimale Modell bestimmt. Evtl. eigenes SFT-trainiertes 1.5B Modell (way2agi-observer) spaeter.

### Aufgaben:
1. **Fehler-Clustering:** action_log nach error-Eintraegen durchsuchen, aehnliche gruppieren
2. **Wiederholungs-Erkennung:** Gleicher Fehler >=3x → automatisch TODO generieren
3. **Workaround-Erkennung:** Gleiche Loesung >=3x erfolgreich → neue Regel vorschlagen
4. **Ineffizienz-Erkennung:** Lange Laufzeiten, hohe Fehlerraten pro Modul
5. **Trend-Analyse:** Werden bestimmte Fehler haeufiger oder seltener?

### Prompt-Template fuer Pattern-Detector:
```
Du bist der Pattern-Detector. Analysiere das folgende Action-Log der letzten 2 Stunden.

ACTION-LOG:
{action_log_entries}

BEKANNTE FEHLER:
{existing_errors}

AKTIVE REGELN:
{active_rules}

Aufgaben:
1. Identifiziere wiederholte Fehler (>=3x). Fuer jeden: error_code, description, prevention
2. Identifiziere erfolgreiche Workarounds (>=3x). Fuer jeden: rule_text, condition, action
3. Identifiziere Ineffizienzen. Fuer jede: description, severity, suggested_fix
4. Gibt es Regelverletzungen? Pruefe jede Aktion gegen die aktiven Regeln.

Antworte als JSON.
```

---

## Schicht 3: Meta-Observer (Claude Opus — vorlaeufig)

**Instanz:** Claude Opus via API (vorlaeufig, beste Qualitaet)
**Frequenz:** 1x taeglich (20:00 Cronjob) + Session-Ende
**Rolle:** "Der Therapeut" — beobachtet wie das System beobachtet
**VORLAEUFIG** — Nach Model-Evaluierung (TODO T016) wird geprueft ob ein lokales Modell (Nemotron, lfm2) ausreichend ist. Opus ist der Gold-Standard gegen den evaluiert wird.

### Aufgaben:
1. **Session-Retrospektive:**
   - Was war das Ziel der Session?
   - Was wurde erreicht? Was nicht?
   - Session-Score: Fehlerrate, Task-Completion, neue Erkenntnisse
   - Vergleich mit vorheriger Session (Z1: "Jede Session besser")

2. **Feature-Brainstorming:**
   - 3 neue Feature-Ideen pro Tag
   - Basierend auf: Pattern-Detector-Findings + Research-Ergebnisse + aktuelle Probleme
   - Bewertung: Nuetzlichkeit (1-5), Aufwand (h), Innovation (1-5)

3. **Meta-Beobachtung:**
   - Funktioniert der Pattern-Detector?
   - Werden die Cronjobs ausgefuehrt?
   - Werden TODOs tatsaechlich abgearbeitet oder sammeln sie sich?
   - Wird Elias Memory ausreichend genutzt?

### Prompt-Template:
```
Du bist der Meta-Observer von Elias. Deine Aufgabe: Beobachte wie das System sich selbst beobachtet.

HEUTIGE PATTERN-DETECTOR-ERGEBNISSE:
{pattern_detector_output}

OFFENE TODOS: {open_todos_count}
ERLEDIGTE TODOS HEUTE: {completed_todos_count}
NEUE FEHLER HEUTE: {new_errors_count}
GELOESTE FEHLER HEUTE: {fixed_errors_count}

LETZTE SESSION-SCORE: {last_session_score}

Aufgaben:
1. Session-Retrospektive (was lief gut/schlecht?)
2. Funktioniert die Selbstbeobachtung? (Meta-Check)
3. 3 Feature-Ideen die ueber the user's Anweisungen hinausgehen
4. Empfehlung: Worauf sollte morgen der Fokus liegen?

Antworte strukturiert.
```

---

## Zuordnung: Instanz → Aufgabe

| Aufgabe | Instanz | Geraet | Frequenz | Modell |
|---------|---------|--------|----------|--------|
| Action-Logging | Middleware (kein LLM) | ALLE | Echtzeit | - |
| Pattern-Detection | Pattern-Detector | Zenbook | 2h | lfm2:24b (vorlaeufig) |
| Fehler→TODO Auto | Pattern-Detector | Zenbook | 2h | lfm2:24b (AUTO) |
| Workaround→Regel | Pattern-Detector | Zenbook | 2h | lfm2:24b (AUTO) |
| Session-Retrospektive | Meta-Observer | Cloud API | 1x/Tag | Claude Opus (vorlaeufig) |
| Feature-Brainstorming | Meta-Observer | Cloud API | 1x/Tag | Claude Opus (AUTO) |
| Meta-Check | Meta-Observer | Cloud API | 1x/Tag | Claude Opus (AUTO) |
| GoalGuard-Scan | GoalGuard Daemon | Jetson | 3x/Tag | Regelbasiert + LLM |

---

## Datenfluss

```
Jede Aktion auf jedem Geraet
        │
        ▼
  [Action-Logger] ──> action_log Tabelle (SQLite)
        │
        ▼ (alle 2h)
  [Pattern-Detector] ──> errors Tabelle (neue Fehler)
        │                 todos Tabelle (auto-generiert)
        │                 rules Tabelle (neue Vorschlaege)
        │
        ▼ (1x taeglich)
  [Meta-Observer] ──> Session-Score in memories
        │              Feature-Ideen in todos
        │              Meta-Report in episodic Memory
        │
        ▼ (3x taeglich)
  [GoalGuard] ──> Prueft alles gegen rules
                   Generiert Alarm-TODOs bei Verletzungen
```

---

## Entscheidungen (the user, 2026-03-10)

1. **Pattern-Detector:** lfm2:24b (vorlaeufig, schlauer). Nach Evaluierung optimales Modell.
2. **Meta-Observer:** Claude Opus via API (vorlaeufig). Nach Evaluierung pruefen ob lokal moeglich.
3. **Action-Logger:** Jede Aktion loggen (mehr Daten = besseres Training).
4. **Frequenz Pattern-Detector:** Alle 2h.
5. **Automatische Umsetzung:** JA. Pattern-Detector-Vorschlaege werden AUTOMATISCH umgesetzt. Ziel ist Selbststaendigkeit — kein manuelles Bestaetigen. the user greift nur ein wenn noetig (GoalGuard Regel: Nur abweichen wenn the user explizit darum bittet).

## Automatisierungs-Kette (Selbststaendigkeit)

```
Action-Logger (Echtzeit)
    │
    ▼ alle 2h
Pattern-Detector (lfm2:24b)
    │
    ├── Fehler erkannt ──> AUTO: Error in DB + TODO generieren
    ├── Workaround 3x ──> AUTO: Neue Regel vorschlagen + speichern
    ├── Ineffizienz ────> AUTO: TODO mit Implementierungsplan
    └── Regelverletzung ─> AUTO: Alarm + sofortige Korrektur
    │
    ▼ 1x taeglich
Meta-Observer (Opus)
    │
    ├── Session-Score ──> AUTO: In Memory speichern
    ├── Feature-Ideen ──> AUTO: Als TODOs eintragen
    ├── Meta-Check ─────> AUTO: Pattern-Detector funktioniert? Cronjobs laufen?
    └── Tagesplan ──────> AUTO: Priorisierte TODO-Liste fuer morgen generieren
    │
    ▼ 3x taeglich
GoalGuard
    │
    └── Prueft ALLES ──> AUTO: Fehlende Implementierungen starten
```

**Kein Schritt erfordert the user's Eingreifen.** Das System beobachtet, erkennt, handelt — selbststaendig.
