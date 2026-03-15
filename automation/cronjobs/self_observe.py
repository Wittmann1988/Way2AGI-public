#!/usr/bin/env python3
"""
Self-Observation Cronjob — Prueft Logs auf Fehler-Muster, reflektiert gut/schlecht.
Laeuft alle 30min, schreibt Beobachtungen in Memory-DB.
"""
import json, urllib.request, sqlite3, datetime, logging, os, sys, uuid, glob

DB_PATH = '/opt/way2agi/memory/memory.db'
LOG_DIR  = '/opt/way2agi/Way2AGI/logs'
LOG_PATH = LOG_DIR + '/self_observe.log'
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger('self_observe')

OLLAMA_LOCAL = 'http://YOUR_PRIMARY_NODE_IP:11434'
OLLAMA_CLOUD  = 'https://api.ollama.com/api/chat'
GROQ_URL      = 'https://api.groq.com/openai/v1/chat/completions'

ERROR_PATTERNS = ['ERROR', 'Traceback', 'Exception', 'FAIL', 'kaputt', 'DOWN', 'timeout', 'ModuleNotFound']


def load_env():
    env_file = '/opt/way2agi/.env'
    env = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    return env


def scan_logs(hours=1):
    """Scan alle .log Dateien der letzten N Stunden auf Fehler-Muster."""
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
    findings = []
    for logfile in glob.glob(LOG_DIR + '/*.log'):
        name = os.path.basename(logfile)
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(logfile))
            if mtime < cutoff:
                continue
            with open(logfile, errors='replace') as f:
                lines = f.readlines()[-200:]
            errors = [l.rstrip() for l in lines if any(p in l for p in ERROR_PATTERNS)]
            ok_lines = [l.rstrip() for l in lines if 'OK' in l or 'erfolgreich' in l or 'gespeichert' in l]
            if errors or ok_lines:
                findings.append({'file': name, 'errors': errors[:5], 'ok': ok_lines[:3]})
        except Exception as e:
            log.warning('Log-Lese-Fehler %s: %s', name, e)
    return findings


def ask_local(prompt, timeout=60):
    try:
        payload = json.dumps({'model': 'qwen3.5:0.8b', 'prompt': prompt,
                               'stream': False, 'options': {'num_predict': 400, 'temperature': 0.3}}).encode()
        req = urllib.request.Request(OLLAMA_LOCAL + '/api/generate', data=payload,
                                     headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.error('Local-Fehler: %s', e)
        return None


def ask_cloud(prompt, env, timeout=90):
    api_key = env.get('OLLAMA_API_KEY', '')
    if not api_key:
        return None
    try:
        import subprocess
        data = json.dumps({'model': 'nemotron-3-super',
                           'messages': [{'role': 'user', 'content': prompt}],
                           'stream': False})
        result = subprocess.run(
            ['curl', '-s', '-X', 'POST', OLLAMA_CLOUD,
             '-H', 'Authorization: Bearer ' + api_key,
             '-H', 'Content-Type: application/json',
             '-d', data],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            log.error('Cloud curl error: %s', result.stderr[:200])
            return None
        return json.loads(result.stdout).get('message', {}).get('content', '')
    except Exception as e:
        log.error('Cloud-Fehler: %s', e)
        return None


def main():
    log.info('=== Self-Observe gestartet: %s ===', datetime.datetime.now().isoformat())
    env = load_env()
    findings = scan_logs(hours=1)
    log.info('Log-Scan: %d Dateien mit Aktivitaet', len(findings))

    if not findings:
        log.info('Keine neuen Ereignisse in den letzten 60min.')
        conn = sqlite3.connect(DB_PATH)
        conn.execute('INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
                     ('self_observe', 'self_observe', 'Keine neuen Logs', 1, 'primary-node'))
        conn.commit()
        conn.close()
        return

    summary = 'Log-Analyse (letzte 60min):\n'
    total_errors = 0
    for f in findings:
        summary += '  %s: %d Fehler, %d OK-Events\n' % (f['file'], len(f['errors']), len(f['ok']))
        if f['errors']:
            summary += '    Fehler: ' + ' | '.join(f['errors'][:2]) + '\n'
        total_errors += len(f['errors'])

    prompt = ('Analysiere diese System-Log-Zusammenfassung eines KI-Systems:\n\n%s\n\n'
              'Was lief gut? Was lief schlecht? Gibt es ein Muster? '
              'Antworte in 3-5 Saetzen auf Deutsch.') % summary[:1200]

    reflection = ask_cloud(prompt, env) or ask_local(prompt)
    if not reflection:
        reflection = 'Keine Reflexion moeglich (kein Modell erreichbar). ' + summary[:200]

    conn = sqlite3.connect(DB_PATH)
    mem_id = 'observe-' + uuid.uuid4().hex[:8]
    conn.execute(
        'INSERT INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)',
        (mem_id, 'Self-Observation %s: %d Fehler. Reflexion: %s' % (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), total_errors, reflection[:400]),
         'episodic', 0.6, 'self_observe')
    )
    if total_errors > 3:
        conn.execute(
            'INSERT INTO todos (id, title, description, priority, status, source) VALUES (?, ?, ?, ?, ?, ?)',
            ('obs-' + uuid.uuid4().hex[:6], 'Self-Observe: Viele Fehler (%d)' % total_errors,
             summary[:400], 80, 'open', 'cronjob')
        )
    conn.execute('INSERT INTO action_log (action_type, module, input_summary, output_summary, success, device) VALUES (?, ?, ?, ?, ?, ?)',
                 ('self_observe', 'self_observe', 'Logs: %d files' % len(findings),
                  'Errors: %d, Reflection: %d chars' % (total_errors, len(reflection)), 1, 'primary-node'))
    conn.commit()
    conn.close()
    log.info('Reflexion: %s', reflection[:200])

    # Titans Memory: Encode surprising observations + periodic replay
    try:
        sys.path.insert(0, CORE_BASE if 'CORE_BASE' in dir() else '/data/way2agi')
        from memory.titans_replay import TitansMemory
        tm = TitansMemory(db_path=DB_PATH)
        surprise = min(1.0, total_errors * 0.15 + 0.2)
        tm.encode(
            'Self-Observation: %d Fehler. %s' % (total_errors, reflection[:300]),
            surprise=surprise,
            metadata={'source': 'self_observe', 'total_errors': total_errors},
        )
        import random
        if random.random() < 0.17:
            replay = tm.sleep_replay()
            log.info('Titans Replay: cons=%d forg=%d str=%d', replay.consolidated, replay.forgotten, replay.strengthened)
    except Exception as e:
        log.debug('Titans nicht verfuegbar (non-critical): %s', e)

    # 3-Layer Consciousness: Observe and learn
    try:
        from agents.consciousness.consciousness_layer import ThreeLayerConsciousness
        c = ThreeLayerConsciousness(db_path=DB_PATH)
        c.observe_and_learn(
            'self_observe_scan',
            'Errors: %d, Reflection: %s' % (total_errors, reflection[:100]),
        )
    except Exception as e:
        log.debug('Consciousness nicht verfuegbar (non-critical): %s', e)

    log.info('=== Self-Observe beendet ===')


if __name__ == '__main__':
    main()
