#!/usr/bin/env python3
"""
GoalGuard Cronjob — Prueft und arbeitet TODOs automatisch ab.
Laeuft 3x taeglich (08:00, 14:00, 20:00) via crontab.

Ablauf:
1. Alle offenen TODOs nach Prioritaet sortiert laden
2. Regelverletzungen pruefen (rules vs. action_log)
3. Neue Fehler → automatisch TODOs generieren
4. Offene TODOs an verfuegbare Modelle/Geraete delegieren
5. Ergebnisse loggen, Status updaten
"""

import sqlite3
import json
import subprocess
import datetime
import os
import sys
import logging
import urllib.request
import urllib.error

DB_PATH = '/opt/way2agi/memory/db/elias_memory.db'
_DB_FALLBACKS = ['/opt/way2agi/memory/memory.db']
LOG_PATH = '/opt/way2agi/memory/logs/goalguard.log'
OLLAMA_LOCAL = 'http://localhost:11434'
NODES = {
    'inference-node': 'http://localhost:11434',
    'desktop': 'http://YOUR_COMPUTE_NODE_IP:8100',
    'npu-node': 'http://YOUR_NPU_NODE_IP:11434',
}

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, mode='a'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('goalguard')


def get_db():
    """Robuste DB-Verbindung mit Fallback-Pfaden."""
    import os as _os
    for db_path in [DB_PATH] + _DB_FALLBACKS:
        try:
            _os.makedirs(_os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if 'rules' in tables and 'todos' in tables:
                # Prevention: Pruefe ob Rules vorhanden, WARNE wenn 0
                rule_count = conn.execute("SELECT COUNT(*) FROM rules WHERE status='active'").fetchone()[0]
                if rule_count == 0:
                    log.critical("WARNUNG: 0 aktive Rules in %s! GoalGuard ist WIRKUNGSLOS ohne Rules.", db_path)
                    log.critical("Pruefe ob die richtige DB verwendet wird oder ob Rules importiert werden muessen.")
                else:
                    log.info("DB verbunden: %s (%d aktive Rules)", db_path, rule_count)
                return conn
            conn.close()
        except Exception as e:
            log.warning("DB %s nicht nutzbar: %s", db_path, e)
    raise RuntimeError("Keine nutzbare DB mit rules+todos gefunden!")



def check_node_health(url, timeout=5):
    """Prueft ob ein Ollama-Node erreichbar ist."""
    try:
        req = urllib.request.Request(url + '/api/tags', method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        models = [m['name'] for m in data.get('models', [])]
        return True, models
    except Exception as e:
        return False, []


def ollama_generate(node_url, model, prompt, system='Du bist ein hilfreicher Assistent.', timeout=120):
    """Sendet Prompt an Ollama und gibt Antwort zurueck."""
    try:
        payload = json.dumps({
            'model': model,
            'prompt': prompt,
            'system': system,
            'stream': False,
            'options': {'temperature': 0.3, 'num_predict': 1024}
        }).encode()
        req = urllib.request.Request(
            node_url + '/api/generate',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data.get('response', '')
    except Exception as e:
        log.error('Ollama Fehler (%s, %s): %s', node_url, model, e)
        return None


def log_action(conn, action_type, module, details, success=True):
    """Loggt Aktion in action_log."""
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
        (action_type, module, details[:500], 1 if success else 0, 'inference-node')
    )
    conn.commit()


def check_rules(conn):
    """Prueft ob aktive Regeln verletzt werden."""
    log.info('=== Regelpruefung ===')
    rules = conn.execute('SELECT id, rule_text, condition, action FROM rules WHERE status="active"').fetchall()
    violations = []

    for rule in rules:
        rule_id = rule['id']

        # R007: Nicht-Erreichbarkeit pruefen
        if rule_id == 'R007':
            for name, url in NODES.items():
                online, models = check_node_health(url)
                if not online:
                    violations.append({
                        'rule_id': rule_id,
                        'description': '%s (%s) nicht erreichbar' % (name, url),
                        'severity': 'high'
                    })
                    log.warning('R007 verletzt: %s nicht erreichbar', name)
                else:
                    log.info('  %s: online (%d Modelle)', name, len(models))

        # R008: Wiederholte Fehler pruefen
        elif rule_id == 'R008':
            repeated = conn.execute(
                'SELECT error_code, description, occurrence_count FROM errors WHERE occurrence_count >= 2 AND status="open"'
            ).fetchall()
            for err in repeated:
                violations.append({
                    'rule_id': rule_id,
                    'description': 'Fehler %s tritt %dx auf: %s' % (err['error_code'], err['occurrence_count'], err['description']),
                    'severity': 'critical'
                })

        # R009: Offene TODOs mit hoher Prio pruefen
        elif rule_id == 'R009':
            overdue = conn.execute(
                'SELECT id, title, priority FROM todos WHERE status="open" AND priority >= 90 AND created_at < datetime("now", "-2 days")'
            ).fetchall()
            for todo in overdue:
                violations.append({
                    'rule_id': rule_id,
                    'description': 'TODO %s (P%d) seit >2 Tagen offen: %s' % (todo['id'], todo['priority'], todo['title']),
                    'severity': 'high'
                })

    return violations


def generate_todos_from_violations(conn, violations):
    """Erstellt automatisch TODOs aus Regelverletzungen."""
    import uuid
    for v in violations:
        existing = conn.execute(
            'SELECT id FROM todos WHERE title LIKE ? AND status="open"',
            ('%' + v['description'][:50] + '%',)
        ).fetchone()
        if existing:
            log.info('  TODO existiert bereits: %s', existing['id'])
            continue

        todo_id = 'T' + str(uuid.uuid4().hex[:6]).upper()
        conn.execute(
            'INSERT INTO todos (id, title, priority, category, status, source, implementation) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (todo_id, 'AUTO: ' + v['description'][:200], 100 if v['severity'] == 'critical' else 80,
             'rule_violation', 'open', 'goalguard',
             'Automatisch generiert aus Verletzung von %s' % v['rule_id'])
        )
        log.info('  Neues TODO: %s — %s', todo_id, v['description'][:80])
    conn.commit()


def process_todos(conn):
    """Arbeitet offene TODOs ab — delegiert an verfuegbare Modelle."""
    log.info('=== TODO-Abarbeitung ===')

    # Verfuegbare Nodes ermitteln
    available = {}
    for name, url in NODES.items():
        online, models = check_node_health(url)
        if online:
            available[name] = {'url': url, 'models': models}
            log.info('  %s: verfuegbar (%s)', name, ', '.join(models[:3]))

    if not available:
        log.error('KEINE Nodes verfuegbar! Abbruch.')
        return

    # Offene TODOs nach Prioritaet
    todos = conn.execute(
        'SELECT id, title, implementation, priority, assigned_to FROM todos WHERE status="open" ORDER BY priority DESC'
    ).fetchall()

    log.info('  %d offene TODOs', len(todos))

    # Pro Durchlauf max 3 TODOs bearbeiten (nicht alles auf einmal)
    processed = 0
    for todo in todos[:3]:
        todo_id = todo['id']
        title = todo['title']
        impl = todo['implementation'] or ''
        assigned = todo['assigned_to'] or 'inference-node'

        log.info('  Bearbeite %s (P%d): %s', todo_id, todo['priority'], title[:60])

        # Waehle Modell basierend auf Zuweisung und Verfuegbarkeit
        node = assigned if assigned in available else next(iter(available))
        node_url = available[node]['url']
        models = available[node]['models']

        # Bevorzuge lfm2 fuer Analyse-Tasks
        model = 'lfm2:latest'
        for m in models:
            if 'lfm2' in m:
                model = m
                break

        # Frage das Modell nach konkretem Implementierungsplan
        prompt = (
            'TODO: %s\n'
            'Beschreibung: %s\n\n'
            'Erstelle einen konkreten, ausfuehrbaren Implementierungsplan mit Schritten. '
            'Antworte als nummerierte Liste. Jeder Schritt muss ein konkreter Befehl oder Code-Aenderung sein.'
        ) % (title, impl)

        system = (
            'Du bist ein Software-Architekt im Way2AGI Projekt. '
            'Erstelle praezise, ausfuehrbare Implementierungsplaene. '
            'Keine Floskeln, nur konkrete Schritte.'
        )

        response = ollama_generate(node_url, model, prompt, system)

        if response:
            # Status auf in_progress setzen und Plan speichern
            conn.execute(
                'UPDATE todos SET status="in_progress", implementation=? WHERE id=?',
                (response[:2000], todo_id)
            )
            log_action(conn, 'todo_process', 'goalguard',
                       'TODO %s delegiert an %s/%s' % (todo_id, node, model))
            log.info('  -> %s delegiert an %s/%s', todo_id, node, model)
            processed += 1
        else:
            log.warning('  -> %s: Keine Antwort von %s/%s', todo_id, node, model)

    conn.commit()
    log.info('  %d TODOs bearbeitet', processed)
    return processed


def generate_report(conn):
    """Erstellt Tagesbericht."""
    stats = {}
    for status in ['open', 'in_progress', 'done', 'blocked']:
        row = conn.execute('SELECT COUNT(*) FROM todos WHERE status=?', (status,)).fetchone()
        stats[status] = row[0]

    errors_open = conn.execute('SELECT COUNT(*) FROM errors WHERE status="open"').fetchone()[0]
    rules_active = conn.execute('SELECT COUNT(*) FROM rules WHERE status="active"').fetchone()[0]

    report = (
        '=== GoalGuard Report %s ===\n'
        'TODOs: %d offen, %d in Arbeit, %d erledigt, %d blockiert\n'
        'Errors: %d offen\n'
        'Rules: %d aktiv\n'
    ) % (
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        stats['open'], stats['in_progress'], stats['done'], stats['blocked'],
        errors_open, rules_active
    )
    log.info(report)
    return report


def main():
    log.info('========================================')
    log.info('GoalGuard Cronjob gestartet: %s', datetime.datetime.now().isoformat())
    log.info('========================================')

    conn = get_db()

    try:
        # 1. Regeln pruefen
        violations = check_rules(conn)
        if violations:
            log.warning('%d Regelverletzungen gefunden!', len(violations))
            generate_todos_from_violations(conn, violations)
        else:
            log.info('Keine Regelverletzungen.')

        # 2. TODOs abarbeiten
        processed = process_todos(conn)

        # 3. Report
        report = generate_report(conn)

        # 4. In action_log schreiben
        log_action(conn, 'goalguard_run', 'goalguard',
                   'Violations: %d, TODOs processed: %d' % (len(violations), processed or 0))

    except Exception as e:
        log.error('GoalGuard Fehler: %s', e, exc_info=True)
        log_action(conn, 'error', 'goalguard', str(e), success=False)
    finally:
        conn.close()

    log.info('GoalGuard Cronjob beendet.')


if __name__ == '__main__':
    main()
