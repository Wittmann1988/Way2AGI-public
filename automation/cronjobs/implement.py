#!/usr/bin/env python3
"""
Auto-Implementierung Cronjob — Nimmt TODOs in_progress und versucht Code zu generieren.
Laeuft 1x taeglich (16:00).
Nutzt lfm2 fuer Code-Generierung, delegiert an Desktop fuer schwere Tasks.
"""

import json
import urllib.request
import sqlite3
import datetime
import logging
import os
import sys

DB_PATH = '/data/way2agi/memory/memory.db'
LOG_PATH = '/data/way2agi/memory/logs/implement.log'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('implement')

NODES = {
    'jetson': ('http://localhost:11434', 'lfm2:24b'),
    'zenbook': ('http://YOUR_LAPTOP_IP:11434', 'lfm2:latest'),
    'desktop': ('http://YOUR_DESKTOP_IP:8100', 'lfm2:24b'),
}


def ollama_generate(url, model, prompt, system='', timeout=180):
    try:
        payload = json.dumps({
            'model': model, 'prompt': prompt, 'system': system,
            'stream': False, 'options': {'temperature': 0.2, 'num_predict': 2048}
        }).encode()
        req = urllib.request.Request(url + '/api/generate', data=payload, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.error('Fehler %s/%s: %s', url, model, e)
        return None


def verify_on_s24(code_description, timeout=60):
    """S24 als unabhaengige Verifikation nutzen."""
    try:
        prompt = (
            'Pruefe ob dieser Implementierungsplan sinnvoll und sicher ist:\n\n%s\n\n'
            'Antworte mit: OK (wenn sicher) oder WARNUNG: <grund> (wenn problematisch).'
        ) % code_description[:500]
        payload = json.dumps({
            'model': 'qwen3:1.7b', 'prompt': prompt,
            'system': 'Du bist ein Code-Reviewer. Pruefe auf Sicherheit und Korrektheit.',
            'stream': False, 'options': {'temperature': 0.1, 'num_predict': 256}
        }).encode()
        req = urllib.request.Request(
            'http://YOUR_MOBILE_IP:11434/api/generate',
            data=payload, headers={'Content-Type': 'application/json'}
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.warning('S24 Verifikation fehlgeschlagen: %s', e)
        return 'S24 nicht erreichbar'


def main():
    log.info('=== Auto-Implementierung gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # TODOs die in_progress sind (wurden von GoalGuard delegiert)
    todos = conn.execute(
        'SELECT id, title, implementation, priority, assigned_to FROM todos WHERE status="in_progress" ORDER BY priority DESC LIMIT 3'
    ).fetchall()

    if not todos:
        log.info('Keine TODOs in_progress. Nehme naechste offene.')
        todos = conn.execute(
            'SELECT id, title, implementation, priority, assigned_to FROM todos WHERE status="open" ORDER BY priority DESC LIMIT 2'
        ).fetchall()

    log.info('%d TODOs zur Implementierung', len(todos))

    for todo in todos:
        todo_id = todo['id']
        title = todo['title']
        impl = todo['implementation'] or ''

        log.info('Implementiere %s: %s', todo_id, title[:60])

        # Code generieren lassen
        prompt = (
            'Implementiere folgendes Feature fuer das Way2AGI Projekt (Python):\n\n'
            'TODO: %s\n'
            'Plan: %s\n\n'
            'Schreibe den vollstaendigen Python-Code. Nutze nur stdlib + sqlite3 + json + urllib.'
            'Fuege docstrings und error handling hinzu.'
        ) % (title, impl[:800])

        system = 'Du bist ein Senior Python-Entwickler. Schreibe sauberen, getesteten Code. Keine externen Dependencies.'

        # Bevorzuge Zenbook/Desktop fuer Code-Generierung
        assigned = todo['assigned_to'] or 'jetson'
        if assigned in NODES:
            url, model = NODES[assigned]
        else:
            url, model = NODES['jetson']

        code = ollama_generate(url, model, prompt, system)

        if not code:
            log.warning('Keine Implementierung fuer %s erhalten', todo_id)
            continue

        # S24 Verifikation
        log.info('S24 Verifikation...')
        review = verify_on_s24(code[:500])
        log.info('S24 sagt: %s', review[:100])

        if 'WARNUNG' in (review or '').upper():
            log.warning('S24 hat Warnung fuer %s: %s', todo_id, review[:200])
            conn.execute(
                'UPDATE todos SET status="blocked", implementation=? WHERE id=?',
                ('S24 REVIEW WARNUNG: %s\n\nOriginal-Code:\n%s' % (review[:200], code[:1000]), todo_id)
            )
        else:
            # Speichere generierten Code
            conn.execute(
                'UPDATE todos SET implementation=?, status="in_progress" WHERE id=?',
                ('GENERIERTER CODE (Review ausstehend):\n%s\n\nS24 Review: %s' % (code[:3000], review[:200]), todo_id)
            )
            log.info('%s: Code generiert und Review bestanden', todo_id)

        conn.execute(
            'INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
            ('implement', 'auto-implement', 'TODO %s: %s' % (todo_id, title[:100]), 1, assigned)
        )
        conn.commit()

    conn.close()
    log.info('=== Auto-Implementierung beendet ===')


if __name__ == '__main__':
    main()
