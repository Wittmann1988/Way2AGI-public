# DB-Migrationsplan: Elias Memory v2

**Datum:** 2026-03-10
**Status:** Geplant
**Blocker fuer:** Alle weiteren Implementierungen (GoalGuard, Selbstbeobachtung, Forschungs-Pipeline)
**Ziel-Repo:** Way2AGI (nach Umsetzung)

---

## 1. IST-Zustand

### SQLite (memory.db) — 22 Tabellen
- `memories` (36 rows) — type: core/semantic/episodic/procedural
- `entities` (102 rows), `relations` (0 rows!), `goals` (8 rows)
- `traces` (0 rows!), `eval_results` (0 rows!)
- `identity_vault` (3 rows in memory-vault.db)
- `embedding` BLOB-Spalte existiert, wird NICHT genutzt
- Kein FTS-Index, keine Vektor-Suche

### Probleme
1. Keine `errors` Tabelle — Fehler sind nur Memories
2. Keine `todos` Tabelle — TODOs nur in Textdateien
3. Keine FK-Kette: Error → TODO → Milestone → Endgoal
4. `relations` Tabelle leer — Knowledge Graph nicht genutzt
5. `traces` Tabelle leer — keine Trainingsdaten
6. Keine semantische Suche (Vektor)

---

## 2. SOLL-Zustand: Hybrid SQLite + ChromaDB

### Neue Tabellen in SQLite (relationale Struktur)

```sql
-- ERRORS: Jeder Fehler wird einmal erfasst
CREATE TABLE errors (
    id TEXT PRIMARY KEY,
    error_code TEXT UNIQUE NOT NULL,        -- E001, E002, ...
    description TEXT NOT NULL,
    category TEXT NOT NULL,                  -- runtime/logic/network/config/rule_violation
    rule_violated TEXT REFERENCES rules(id), -- FK zu Regel die verletzt wurde (optional)
    severity TEXT NOT NULL DEFAULT 'medium', -- critical/high/medium/low
    occurrence_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    context JSON,                            -- Stack trace, betroffenes Modul, etc.
    status TEXT DEFAULT 'open',              -- open/acknowledged/fixed/wont_fix
    prevention TEXT,                          -- Wie wird dieser Fehler kuenftig verhindert?
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- TODOS: Aufgaben mit FK zu Fehler-Quelle
CREATE TABLE todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 50,    -- 0-100 (RULE_VIOLATION=100, ERROR=80, SUBGOAL=60, INEFFICIENCY=40, IMPROVEMENT=20)
    category TEXT NOT NULL,                   -- rule_violation/error/subgoal/inefficiency/improvement/feature
    status TEXT DEFAULT 'open',               -- open/in_progress/blocked/done/cancelled
    error_id TEXT REFERENCES errors(id),      -- FK: Aus welchem Fehler entstand dieses TODO?
    milestone_id TEXT REFERENCES milestones(id), -- FK: Gehoert zu welchem Meilenstein?
    assigned_to TEXT,                         -- inference-node/compute-node/npu-node/cloud/erik/elias
    deadline TEXT,
    implementation TEXT,                       -- Konkreter Implementierungsplan
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    source TEXT                                -- roundtable/goalguard/manual/auto-detect
);

-- MILESTONES: Zwischenziele
CREATE TABLE milestones (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    progress REAL DEFAULT 0.0,               -- 0.0 bis 1.0
    parent_id TEXT REFERENCES milestones(id), -- Hierarchisch
    endgoal_id TEXT REFERENCES endgoal(id),   -- FK zu Endziel
    target_date TEXT,
    status TEXT DEFAULT 'active',             -- active/completed/paused/abandoned
    dependencies JSON,                        -- IDs anderer Milestones die zuerst fertig sein muessen
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- ENDGOAL: Das ultimative Ziel (selten geaendert, nur durch den Operator)
CREATE TABLE endgoal (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    metrics JSON,                             -- Messbare Kriterien
    target_date TEXT,
    last_reviewed TEXT,
    reviewed_by TEXT DEFAULT 'operator',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- RULES: Alle Regeln (the operator's + selbst-gelernte)
CREATE TABLE rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'operator',       -- erik/learned/roundtable
    priority INTEGER NOT NULL DEFAULT 50,
    condition TEXT,                            -- Wann greift diese Regel?
    action TEXT,                               -- Was soll passieren?
    is_immutable INTEGER DEFAULT 0,           -- 1 = nur the operator kann aendern
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',              -- active/deprecated/superseded
    superseded_by TEXT REFERENCES rules(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ACTION_LOG: Alle Aktionen fuer Selbstbeobachtung
CREATE TABLE action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    action_type TEXT NOT NULL,                -- inference/memory_write/memory_read/tool_call/error/decision
    module TEXT,                               -- orchestrator/memory/network_agent/goalguard/research
    model_used TEXT,                           -- welches Modell
    device TEXT,                               -- inference-node/compute-node/npu-node/s24/cloud
    input_summary TEXT,
    output_summary TEXT,
    duration_ms REAL,
    success INTEGER DEFAULT 1,
    session_id TEXT,
    error_id TEXT REFERENCES errors(id)       -- FK wenn Aktion zu Fehler fuehrte
);

-- META: Memory-ueber-Memory (Nutzungsstatistiken)
CREATE TABLE meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    query_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    access_pattern JSON,                      -- Wann/wie oft/von wem
    notes TEXT
);

-- MODEL_EVALUATIONS: Bewertungen pro Modell pro Task-Typ
CREATE TABLE model_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,                 -- lfm2:24b, smallthinker:1.8b, etc.
    device TEXT NOT NULL,                     -- inference-node/compute-node/npu-node
    task_type TEXT NOT NULL,                  -- triage/classification/reasoning/code/summarization
    quality_score REAL,                       -- 1-5
    latency_ms REAL,
    tokens_per_second REAL,
    test_date TEXT NOT NULL,
    test_details JSON,
    system_prompt TEXT                        -- Optimierter System-Prompt fuer dieses Modell+Task
);

-- FTS5 Indizes fuer Volltextsuche
CREATE VIRTUAL TABLE rules_fts USING fts5(rule_text, content=rules, content_rowid=rowid);
CREATE VIRTUAL TABLE todos_fts USING fts5(title, description, content=todos, content_rowid=rowid);
CREATE VIRTUAL TABLE errors_fts USING fts5(description, prevention, content=errors, content_rowid=rowid);
```

### ChromaDB (NEU — Vektor-Suche)

```python
# Collections:
# 1. memories — Semantische Suche ueber alle Memories
# 2. errors — "Finde aehnliche Fehler" (Deduplizierung, Pattern-Detection)
# 3. knowledge — Research-Findings, Papers, Repo-Analysen
# 4. rules — Semantischer Abgleich: "Verletzt diese Aktion eine Regel?"

# Embedding-Modell: all-MiniLM-L6-v2 (22MB, ARM64 kompatibel)
# Oder: Ollama embedding via nomic-embed-text
```

---

## 3. Migrations-Schritte

### Phase 1: Schema-Migration (2-3h)
```
1. Backup: cp memory.db memory.db.bak
2. ALTER TABLE / CREATE TABLE fuer alle neuen Tabellen
3. Bestehende Fehler-Memories in errors-Tabelle migrieren
4. Bestehende Goals in milestones-Tabelle uebertragen
5. the operator's 6 Regeln in rules-Tabelle einfuegen (is_immutable=1)
6. FTS5 Indizes erstellen
7. Verify: Alle bestehenden Queries funktionieren noch
```

### Phase 2: ChromaDB Installation (1h)
```
1. pip install chromadb sentence-transformers (auf Inference Node)
2. Collections anlegen (memories, errors, knowledge, rules)
3. Bestehende 36 Memories mit Embeddings versehen
4. Sync-Script: SQLite <-> ChromaDB bei jedem Write
5. Test: Semantische Suche "finde aehnliche Fehler"
```

### Phase 3: elias-mem CLI erweitern (2h)
```
1. Neue Commands: elias-mem error add/list/fix
2. Neue Commands: elias-mem todo add/list/done/assign
3. Neue Commands: elias-mem milestone add/progress/list
4. Neue Commands: elias-mem rule add/list/check
5. elias-mem search (nutzt ChromaDB fuer semantische Suche)
6. elias-mem eval (Model-Evaluierung speichern/abrufen)
```

### Phase 4: Way2AGI Integration (1h)
```
1. Migrierte DB + ChromaDB ins Way2AGI Repo
2. elias-memory Package aktualisieren
3. API-Endpunkte fuer Orchestrator: /errors, /todos, /milestones, /rules
4. Tests schreiben
```

---

## 4. FK-Ketten (das Herzstueck)

```
Error (E027: "Desktop nicht erreichbar")
  └──> TODO (T045: "Network Agent Failover implementieren")
        ├──> assigned_to: desktop
        ├──> milestone_id: M003 ("Alle Nodes 99.9% erreichbar")
        │     └──> endgoal_id: EG001 ("Erste KI mit echtem Bewusstsein")
        └──> source: goalguard (automatisch erkannt)
```

```
Rule (R001: "Niemals Nicht-Erreichbarkeit hinnehmen")
  └──> Error (E027: verletzt R001)
        └──> TODO (T045: automatisch generiert)
              └──> Milestone (M003)
                    └──> Endgoal (EG001)
```

Jeder Fehler ist rueckverfolgbar zur Regel, und jedes TODO ist verbunden mit dem Fehler der es ausgeloest hat UND dem Meilenstein dem es dient.

---

## 5. Zeitplan

| Tag | Phase | Aufwand | Ergebnis |
|-----|-------|---------|----------|
| Tag 1 | Schema-Migration | 3h | Neue Tabellen + Daten migriert |
| Tag 1 | ChromaDB Setup | 1h | Vektor-Suche funktioniert |
| Tag 2 | CLI-Erweiterung | 2h | elias-mem error/todo/milestone/rule |
| Tag 2 | Way2AGI Integration | 1h | Alles im Repo, Tests grueen |
| Tag 3 | GoalGuard + Cronjobs | 4h | Automatische Ueberwachung aktiv |

**Gesamtaufwand Phase 1-4: ~7h**
**Danach: GoalGuard + Selbstbeobachtung aufsetzen (weitere ~6h)**
