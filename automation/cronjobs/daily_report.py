#!/usr/bin/env python3
"""
Daily Report Cronjob — Taegliche Zusammenfassung um 06:00.
Was wurde gestern erledigt? Was ist heute offen?
"""
import json, urllib.request, sqlite3, datetime, logging, os, sys, uuid

DB_PATH = '/opt/way2agi/memory/memory.db'
LOG_PATH = '/opt/way2agi/Way2AGI/logs/daily_report.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger('daily_report')

OLLAMA_LOCAL = 'http://YOUR_PRIMARY_NODE_IP:11434'
OLLAMA_CLOUD  = 'https://api.ollama.com/api/chat'
GROQ_URL      = 'https://api.groq.com/openai/v1/chat/completions'


def load_env():
    env = {}
    for env_file in ['/opt/way2agi/.env']:
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env[k.strip()] = v.strip()
    return env


def gather_data(conn):
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    today = datetime.date.today().isoformat()

    actions = conn.execute(
        "SELECT action_type, module, success, output_summary FROM action_log "
        "WHERE date(timestamp) = ? ORDER BY timestamp DESC LIMIT 30", (yesterday,)
    ).fetchall()

    completed_todos = conn.execute(
        "SELECT title FROM todos WHERE status='done' AND date(completed_at) = ?", (yesterday,)
    ).fetchall()

    open_todos = conn.execute(
        "SELECT title, priority FROM todos WHERE status='open' ORDER BY priority DESC LIMIT 10"
    ).fetchall()

    memories = conn.execute(
        "SELECT content FROM memories WHERE date(created_at) = ? ORDER BY importance DESC LIMIT 5", (yesterday,)
    ).fetchall()

    errors = conn.execute(
        "SELECT title FROM todos WHERE source='cronjob' AND status='open' "
        "AND date(created_at) >= ? ORDER BY priority DESC LIMIT 5", (yesterday,)
    ).fetchall()

    return {
        'actions': actions, 'completed': completed_todos,
        'open': open_todos, 'memories': memories, 'errors': errors
    }


def ask_cloud(prompt, env, timeout=120):
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
        log.error('Cloud: %s', e)
        return None


def ask_groq(prompt, env, timeout=60):
    api_key = env.get('GROQ_API_KEY', '')
    if not api_key:
        return None
    try:
        payload = json.dumps({'model': 'llama-3.3-70b-versatile',
                               'messages': [{'role': 'user', 'content': prompt}],
                               'max_tokens': 600}).encode()
        req = urllib.request.Request(GROQ_URL, data=payload,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer ' + api_key})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())['choices'][0]['message']['content']
    except Exception as e:
        log.error('Groq: %s', e)
        return None


def ask_local(prompt, timeout=90):
    try:
        payload = json.dumps({'model': 'lfm2:24b', 'prompt': prompt,
                               'stream': False, 'options': {'num_predict': 600, 'temperature': 0.3}}).encode()
        req = urllib.request.Request(OLLAMA_LOCAL + '/api/generate', data=payload,
                                     headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.error('Local: %s', e)
        return None


def main():
    log.info('=== Daily Report gestartet: %s ===', datetime.datetime.now().isoformat())
    env = load_env()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    data = gather_data(conn)

    # Build data summary
    actions_txt = '\n'.join(['  [%s] %s/%s: %s' % (
        'OK' if r['success'] else 'FAIL', r['action_type'], r['module'],
        (r['output_summary'] or '')[:80]) for r in data['actions']]) or '  (keine)'

    completed_txt = '\n'.join(['  - ' + r['title'] for r in data['completed']]) or '  (keine)'
    open_txt = '\n'.join(['  [Prio %d] %s' % (r['priority'], r['title']) for r in data['open']]) or '  (keine)'
    memories_txt = '\n'.join(['  ' + r['content'][:100] for r in data['memories']]) or '  (keine)'
    errors_txt = '\n'.join(['  - ' + r['title'] for r in data['errors']]) or '  (keine)'

    raw_report = (
        '=== WAY2AGI DAILY REPORT: %s ===\n\n'
        'GESTERN AUSGEFUEHRT:\n%s\n\n'
        'ABGESCHLOSSENE TODOS:\n%s\n\n'
        'NEUE ERKENNTNISSE:\n%s\n\n'
        'FEHLER/PROBLEME:\n%s\n\n'
        'OFFENE TODOS (Top 10):\n%s\n'
    ) % (datetime.date.today().isoformat(), actions_txt, completed_txt, memories_txt, errors_txt, open_txt)

    log.info(raw_report)

    prompt = ('Hier ist der Raw-Report von gestern fuer das Way2AGI Projekt:\n\n%s\n\n'
              'Erstelle eine knappe Zusammenfassung (max 5 Saetze) auf Deutsch: '
              'Was war wichtig? Was blockiert? Was kommt als naechstes?') % raw_report[:2000]

    summary = (ask_cloud(prompt, env) or ask_groq(prompt, env) or ask_local(prompt)
               or 'Keine KI-Zusammenfassung verfuegbar.')

    mem_id = 'dailyrep-' + uuid.uuid4().hex[:8]
    full_content = raw_report[:800] + '\n\nKI-Zusammenfassung: ' + summary[:400]
    conn.execute(
        'INSERT INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)',
        (mem_id, full_content, 'episodic', 0.9, 'daily_report')
    )
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, output_summary, success, device) VALUES (?, ?, ?, ?, ?, ?)',
        ('daily_report', 'daily_report',
         'Actions: %d, Todos-open: %d' % (len(data['actions']), len(data['open'])),
         'Report: %d chars' % len(full_content), 1, 'primary-node')
    )
    conn.commit()
    conn.close()
    log.info('KI-Zusammenfassung: %s', summary[:300])
    log.info('Report gespeichert: %s', mem_id)
    log.info('=== Daily Report beendet ===')


if __name__ == '__main__':
    main()
