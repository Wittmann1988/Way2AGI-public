#!/usr/bin/env python3
"""
Feature-Tester Cronjob — Health-Checks fuer alle Endpoints/Features.
Laeuft alle 30min, schreibt Fehler als TODOs.
"""
import json, urllib.request, sqlite3, datetime, logging, os, sys, uuid

DB_PATH = '/opt/way2agi/memory/memory.db'
LOG_PATH = '/opt/way2agi/Way2AGI/logs/feature_tester.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger('feature_tester')

ENDPOINTS = [
    {'name': 'ollama_local_tags',    'url': 'http://YOUR_PRIMARY_NODE_IP:11434/api/tags',   'method': 'GET',  'required': True},
    {'name': 'ollama_local_generate','url': 'http://YOUR_PRIMARY_NODE_IP:11434/api/generate','method': 'POST',
     'body': {'model': 'qwen3.5:0.8b', 'prompt': 'ping', 'stream': False, 'options': {'num_predict': 5}}, 'required': True},
    {'name': 'ollama_desktop_tags',  'url': 'http://YOUR_COMPUTE_NODE_IP:11434/api/tags',   'method': 'GET',  'required': False},
    {'name': 'orchestrator_health',  'url': 'http://YOUR_PRIMARY_NODE_IP:8150/health',       'method': 'GET',  'required': False},
    {'name': 'db_readable',          'url': None, 'method': 'DB', 'required': True},
]


def check_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('SELECT COUNT(*) FROM memories').fetchone()
        conn.close()
        return True
    except Exception as e:
        log.error('DB-Fehler: %s', e)
        return False


def check_endpoint(ep, timeout=10):
    if ep['method'] == 'DB':
        return check_db()
    try:
        if ep['method'] == 'POST':
            body = json.dumps(ep.get('body', {})).encode()
            req = urllib.request.Request(ep['url'], data=body,
                                         headers={'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(ep['url'])
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status == 200
    except Exception as e:
        log.warning('%s: %s', ep['name'], e)
        return False


def already_reported(conn, name):
    row = conn.execute(
        "SELECT id FROM todos WHERE title LIKE ? AND status='open' AND created_at > datetime('now', '-1 hour')",
        ('%Feature: ' + name + '%',)
    ).fetchone()
    return row is not None


def main():
    log.info('=== Feature-Tester gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)
    results = {}
    failed_required = []

    for ep in ENDPOINTS:
        ok = check_endpoint(ep)
        results[ep['name']] = ok
        icon = 'OK' if ok else 'FAIL'
        log.info('  %-30s %s', ep['name'], icon)
        if not ok:
            if not already_reported(conn, ep['name']):
                prio = 100 if ep['required'] else 50
                conn.execute(
                    'INSERT INTO todos (id, title, description, priority, status, source) VALUES (?, ?, ?, ?, ?, ?)',
                    ('ft-' + uuid.uuid4().hex[:6],
                     'Feature: %s ausgefallen' % ep['name'],
                     'Endpoint %s nicht erreichbar um %s' % (ep.get('url', 'DB'), datetime.datetime.now().isoformat()),
                     prio, 'open', 'cronjob')
                )
            if ep['required']:
                failed_required.append(ep['name'])

    ok_count = sum(1 for v in results.values() if v)
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, output_summary, success, device) VALUES (?, ?, ?, ?, ?, ?)',
        ('feature_test', 'feature_tester',
         '%d Endpoints geprueft' % len(ENDPOINTS),
         '%d OK, %d FAIL (required down: %s)' % (ok_count, len(ENDPOINTS) - ok_count, ', '.join(failed_required) or 'keine'),
         1 if not failed_required else 0, 'primary-node')
    )
    conn.commit()
    conn.close()
    log.info('Ergebnis: %d/%d OK. Required-Failures: %s', ok_count, len(ENDPOINTS),
             ', '.join(failed_required) or 'keine')
    log.info('=== Feature-Tester beendet ===')


if __name__ == '__main__':
    main()
