#!/usr/bin/env python3
"""
Evolution Cronjob Wrapper — startet self_evolving_engine mit korrektem PYTHONPATH.
Umgeht ModuleNotFoundError: 'core' nicht im Python-Pfad.
"""

import subprocess
import sys
import os
import logging
import datetime
import sqlite3
import uuid

DB_PATH = '/opt/way2agi/memory/memory.db'
LOG_PATH = '/opt/way2agi/Way2AGI/logs/evolution.log'
CORE_BASE = '/opt/way2agi'
ENGINE_PATH = '/opt/way2agi/core/evolution/self_evolving_engine.py'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('evolution')


def write_todo(conn, title, desc):
    conn.execute(
        'INSERT INTO todos (id, title, description, priority, status, source) VALUES (?, ?, ?, ?, ?, ?)',
        ('evo-' + uuid.uuid4().hex[:6], title, desc, 100, 'open', 'cronjob')
    )


def main():
    log.info('=== Evolution-Wrapper gestartet: %s ===', datetime.datetime.now().isoformat())

    if not os.path.exists(ENGINE_PATH):
        log.error('self_evolving_engine.py nicht gefunden: %s', ENGINE_PATH)
        conn = sqlite3.connect(DB_PATH)
        write_todo(conn, 'Evolution: Engine fehlt', 'self_evolving_engine.py nicht gefunden unter ' + ENGINE_PATH)
        conn.commit()
        conn.close()
        sys.exit(1)

    env = os.environ.copy()
    # Setze PYTHONPATH damit 'import core' funktioniert
    existing_path = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = CORE_BASE + (':' + existing_path if existing_path else '')
    # Lade .env Keys
    env_file = '/opt/way2agi/.env'
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()

    log.info('PYTHONPATH=%s', env['PYTHONPATH'])
    log.info('Starte self_evolving_engine...')

    try:
        result = subprocess.run(
            [sys.executable, ENGINE_PATH],
            env=env,
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.stdout:
            log.info('STDOUT:\n%s', result.stdout[-2000:])
        if result.stderr:
            log.warning('STDERR:\n%s', result.stderr[-1000:])

        if result.returncode == 0:
            log.info('Evolution erfolgreich abgeschlossen.')
        else:
            log.error('Evolution fehlgeschlagen (returncode %d)', result.returncode)
            conn = sqlite3.connect(DB_PATH)
            write_todo(conn,
                       'Evolution: Fehler beim Ausfuehren',
                       'ReturnCode %d. Fehler: %s' % (result.returncode, result.stderr[-500:]))
            conn.commit()
            conn.close()
    except subprocess.TimeoutExpired:
        log.error('Evolution Timeout nach 600s!')
        conn = sqlite3.connect(DB_PATH)
        write_todo(conn, 'Evolution: Timeout', 'self_evolving_engine lief >600s ohne Ergebnis')
        conn.commit()
        conn.close()
    except Exception as e:
        log.error('Unerwarteter Fehler: %s', e)

    # GEA Group-Evolving Agents (neu: Paper 2602.04837)
    log.info('Starte GEA Group-Evolving cycle...')
    try:
        sys.path.insert(0, CORE_BASE)
        from core.evolution.group_evolve import GroupEvolvingEngine
        import asyncio
        engine = GroupEvolvingEngine(db_path=DB_PATH)
        gea_result = asyncio.run(engine.evolve_cycle(
            "Automatische Evolution: Analysiere aktuelle Systemleistung und schlage Verbesserungen vor",
            agent_id="evolution_cron",
        ))
        log.info('GEA Ergebnis: score=%.2f lessons=%s', gea_result["score"], gea_result["lessons"])
    except Exception as e:
        log.warning('GEA nicht verfuegbar (non-critical): %s', e)

    log.info('=== Evolution-Wrapper beendet ===')


if __name__ == '__main__':
    main()
