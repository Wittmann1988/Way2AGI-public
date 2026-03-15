#!/usr/bin/env python3
"""
Nightwatch Cronjob — Prueft alle 30min ob Services laufen.
Erstellt Error-TODOs in DB bei Problemen.
"""
import json, urllib.request, sqlite3, datetime, logging, os, sys, uuid, subprocess

DB_PATH = '/opt/way2agi/memory/memory.db'
LOG_PATH = '/opt/way2agi/Way2AGI/logs/nightwatch.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger('nightwatch')

SERVICES = [
    {'name': 'ollama_local',   'url': 'http://YOUR_PRIMARY_NODE_IP:11434/api/tags',  'required': True},
    {'name': 'ollama_desktop', 'url': 'http://YOUR_COMPUTE_NODE_IP:11434/api/tags',  'required': False},
    {'name': 'orchestrator',   'url': 'http://YOUR_PRIMARY_NODE_IP:8150/health',      'required': False},
]


def check_service(svc):
    try:
        req = urllib.request.Request(svc['url'])
        resp = urllib.request.urlopen(req, timeout=8)
        return resp.status == 200
    except Exception as e:
        log.warning('%s nicht erreichbar: %s', svc['name'], e)
        return False


def already_reported(conn, name):
    row = conn.execute(
        "SELECT id FROM todos WHERE title LIKE ? AND status='open' AND created_at > datetime('now', '-2 hours')",
        ('%Nightwatch: ' + name + '%',)
    ).fetchone()
    return row is not None


def write_todo(conn, title, desc):
    conn.execute(
        'INSERT INTO todos (id, title, description, priority, status, source) VALUES (?, ?, ?, ?, ?, ?)',
        ('nw-' + uuid.uuid4().hex[:6], title, desc, 100, 'open', 'cronjob')
    )


def main():
    log.info('=== Nightwatch gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)
    results = {}
    for svc in SERVICES:
        ok = check_service(svc)
        results[svc['name']] = ok
        status = 'OK' if ok else 'DOWN'
        log.info('  %-20s %s', svc['name'], status)
        if not ok and svc['required'] and not already_reported(conn, svc['name']):
            write_todo(conn,
                       'Nightwatch: %s DOWN' % svc['name'],
                       'Service %s nicht erreichbar um %s' % (svc['url'], datetime.datetime.now().isoformat()))
    down_required = [s['name'] for s in SERVICES if s['required'] and not results.get(s['name'])]
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, output_summary, success, device) VALUES (?, ?, ?, ?, ?, ?)',
        ('nightwatch_check', 'nightwatch',
         'Services: %d geprueft' % len(SERVICES),
         'DOWN: %s' % (', '.join(down_required) or 'keine'),
         1 if not down_required else 0, 'primary-node')
    )
    conn.commit()
    conn.close()
    log.info('Ergebnis: %d/%d Services OK', sum(results.values()), len(results))
    log.info('=== Nightwatch beendet ===')


if __name__ == '__main__':
    main()
