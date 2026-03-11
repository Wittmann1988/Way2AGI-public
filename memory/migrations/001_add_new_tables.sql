-- Migration 001: Neue Tabellen fuer Errors, TODOs, Milestones, Rules, etc.
-- Datum: 2026-03-10
-- Beschreibung: Erweitert Elias Memory um relationale FK-Ketten

CREATE TABLE IF NOT EXISTS errors (
    id TEXT PRIMARY KEY,
    error_code TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'runtime',
    rule_violated TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    occurrence_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    context TEXT,
    status TEXT DEFAULT 'open',
    prevention TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 50,
    category TEXT NOT NULL DEFAULT 'improvement',
    status TEXT DEFAULT 'open',
    error_id TEXT REFERENCES errors(id),
    milestone_id TEXT REFERENCES milestones(id),
    assigned_to TEXT,
    deadline TEXT,
    implementation TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    source TEXT DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    progress REAL DEFAULT 0.0,
    parent_id TEXT,
    endgoal_id TEXT,
    target_date TEXT,
    status TEXT DEFAULT 'active',
    dependencies TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS endgoal (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    metrics TEXT,
    target_date TEXT,
    last_reviewed TEXT,
    reviewed_by TEXT DEFAULT 'erik',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'erik',
    priority INTEGER NOT NULL DEFAULT 50,
    condition TEXT,
    action TEXT,
    is_immutable INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    action_type TEXT NOT NULL,
    module TEXT,
    model_used TEXT,
    device TEXT,
    input_summary TEXT,
    output_summary TEXT,
    duration_ms REAL,
    success INTEGER DEFAULT 1,
    session_id TEXT,
    error_id TEXT REFERENCES errors(id)
);

CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    query_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    access_pattern TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    device TEXT NOT NULL,
    task_type TEXT NOT NULL,
    quality_score REAL,
    latency_ms REAL,
    tokens_per_second REAL,
    test_date TEXT NOT NULL DEFAULT (datetime('now')),
    test_details TEXT,
    system_prompt TEXT
);
