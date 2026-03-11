-- Consciousness Agent Schema
-- Datum: 2026-03-10
-- Beschreibung: Tabellen fuer den Consciousness Agent (Wirkketten, Intentionen, Research, SVT)

-- Intentions als First-Class Objects
CREATE TABLE IF NOT EXISTS intentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    priority REAL DEFAULT 0.5,
    decay_rate REAL DEFAULT 0.05,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activated TIMESTAMP,
    linked_goal TEXT,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'consciousness',
    impact_score REAL DEFAULT 0.0
);

-- Consciousness Decision Log
CREATE TABLE IF NOT EXISTS consciousness_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decision_type TEXT NOT NULL,
    curiosity_score REAL,
    confidence_score REAL,
    observation TEXT,
    action_taken TEXT,
    expected_outcome TEXT,
    actual_outcome TEXT,
    kpi_impact REAL,
    wirkkette TEXT
);

-- Research Queue
CREATE TABLE IF NOT EXISTS research_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis TEXT NOT NULL,
    priority REAL DEFAULT 0.5,
    curiosity_score REAL,
    status TEXT DEFAULT 'pending',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started TIMESTAMP,
    completed TIMESTAMP,
    result TEXT,
    validated INTEGER DEFAULT 0,
    improvement_pct REAL
);

-- System Improvement Tracker (SVT)
CREATE TABLE IF NOT EXISTS system_improvements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_by TEXT DEFAULT 'consciousness',
    description TEXT NOT NULL,
    category TEXT,
    test_method TEXT,
    baseline_value REAL,
    improved_value REAL,
    improvement_pct REAL,
    status TEXT DEFAULT 'proposed',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated TIMESTAMP,
    deployed TIMESTAMP
);
