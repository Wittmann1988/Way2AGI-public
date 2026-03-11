#!/usr/bin/env python3
"""
Auto-Roundtable Cronjob — Nimmt Research-Findings, fragt alle Modelle.
Laeuft 1x taeglich (12:00) nach Research (07:00).
"""

import json
import urllib.request
import sqlite3
import datetime
import logging
import os
import sys
import uuid

DB_PATH = '/data/way2agi/memory/memory.db'
LOG_PATH = '/data/way2agi/memory/logs/roundtable.log'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('roundtable')

MODELS = {
    'jetson_lfm2': ('http://localhost:11434', 'lfm2:24b'),
    'jetson_nemotron': ('http://localhost:11434', 'nemotron-mini:latest'),
    'zenbook_lfm2': ('http://YOUR_LAPTOP_IP:11434', 'lfm2:latest'),
    'zenbook_smallthinker': ('http://YOUR_LAPTOP_IP:11434', 'mannix/smallthinker-abliterated:latest'),
}


def ollama_ask(url, model, prompt, system='', timeout=120):
    try:
        payload = json.dumps({
            'model': model, 'prompt': prompt, 'system': system,
            'stream': False, 'options': {'temperature': 0.4, 'num_predict': 1024}
        }).encode()
        req = urllib.request.Request(url + '/api/generate', data=payload, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.error('Fehler %s/%s: %s', url, model, e)
        return None


def main():
    log.info('=== Auto-Roundtable gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Lade neueste Research-Findings (letzte 24h)
    findings = conn.execute(
        'SELECT content FROM memories WHERE namespace="research" AND created_at > datetime("now", "-1 day") ORDER BY created_at DESC LIMIT 10'
    ).fetchall()

    if not findings:
        log.info('Keine neuen Research-Findings. Nutze offene TODOs statt dessen.')
        todos = conn.execute('SELECT title, implementation FROM todos WHERE status="open" ORDER BY priority DESC LIMIT 5').fetchall()
        context = '\n'.join(['- %s: %s' % (t['title'], (t['implementation'] or '')[:100]) for t in todos])
    else:
        context = '\n'.join([f['content'][:200] for f in findings])

    prompt = (
        'Kontext (Research-Findings oder offene TODOs):\n%s\n\n'
        'Frage: Welche konkreten Implementierungen oder Features leiten sich daraus ab fuer ein Projekt das:\n'
        '- KI-Bewusstsein baut (Self-Mirroring, Identity)\n'
        '- Multi-Agent-Orchestrierung nutzt (Micro-Agents, feingranular)\n'
        '- Self-Improvement implementiert (Traces -> Training -> bessere Modelle)\n\n'
        'Antworte mit max 3 konkreten Vorschlaegen, je mit: Name, Beschreibung, Aufwand (h), Prioritaet (1-5).'
    ) % context

    system = 'Du bist ein KI-Architekt. Antworte praezise und konkret.'

    # Alle Modelle befragen
    responses = {}
    for name, (url, model) in MODELS.items():
        log.info('Befrage %s (%s)...', name, model)
        resp = ollama_ask(url, model, prompt, system)
        if resp:
            responses[name] = resp
            log.info('  %s: %d Zeichen', name, len(resp))
        else:
            log.warning('  %s: keine Antwort', name)

    if not responses:
        log.error('Keine Modelle haben geantwortet!')
        conn.close()
        return

    # Konsens zusammenfassen (via lfm2)
    consensus_prompt = 'Hier sind Antworten von %d Modellen zu moeglichen Implementierungen:\n\n' % len(responses)
    for name, resp in responses.items():
        consensus_prompt += '--- %s ---\n%s\n\n' % (name, resp[:500])
    consensus_prompt += 'Erstelle einen Konsens: Welche Vorschlaege kommen mehrfach vor? Was ist am wichtigsten? Erstelle 3 priorisierte TODO-Vorschlaege.'

    consensus = ollama_ask('http://localhost:11434', 'lfm2:24b', consensus_prompt, system, timeout=180)

    # In Memory speichern
    mem_id = 'roundtable-' + uuid.uuid4().hex[:8]
    content = 'Auto-Roundtable %s: %d Modelle befragt. Konsens: %s' % (
        datetime.datetime.now().strftime('%Y-%m-%d'), len(responses), (consensus or 'Kein Konsens')[:500]
    )
    conn.execute(
        'INSERT INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)',
        (mem_id, content, 'episodic', 0.8, 'roundtable')
    )
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
        ('roundtable_run', 'roundtable', 'Models: %d, Findings: %d' % (len(responses), len(findings)), 1, 'jetson')
    )
    conn.commit()
    conn.close()

    log.info('Konsens gespeichert: %s', mem_id)
    log.info('=== Auto-Roundtable beendet ===')


if __name__ == '__main__':
    main()
