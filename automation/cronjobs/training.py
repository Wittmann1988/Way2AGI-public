#!/usr/bin/env python3
"""
Training Cronjob — Alle 5 Tage Traces sammeln und Training auf Desktop (YOUR_GPU) starten.
Trainiert: memory-agent, orchestrator-agent, consciousness-agent.
"""

import json
import urllib.request
import sqlite3
import datetime
import logging
import os
import sys
import subprocess

DB_PATH = '/data/way2agi/memory/memory.db'
LOG_PATH = '/data/way2agi/memory/logs/training.log'
TRACES_DIR = '/data/traces'
DESKTOP_SSH = 'YOUR_SSH_USER@YOUR_DESKTOP_IP'
# WSL2 Ubuntu auf Desktop fuer GPU-Training (YOUR_GPU, CUDA 13.0)
DESKTOP_WSL_DISTRO = 'Ubuntu-22.04'
DESKTOP_WSL_PROJECT = '/home/erik/Way2AGI'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(TRACES_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('training')

MODELS_TO_TRAIN = [
    {
        'name': 'way2agi-memory-agent',
        'description': 'Memory-Agent: Speichern, Abrufen, Verknuepfen von Wissen',
        'base_model': 'qwen3:1.7b',
        'trace_filter': 'memory',
    },
    {
        'name': 'way2agi-orchestrator',
        'description': 'Orchestrator: Task-Zerlegung, Model-Routing, Pipeline-Management',
        'base_model': 'smallthinker:1.8b',
        'trace_filter': 'orchestrat',
    },
    {
        'name': 'way2agi-consciousness',
        'description': 'Consciousness-Agent: Self-Mirroring, Identity, Reflexion',
        'base_model': 'smallthinker:1.8b',
        'trace_filter': 'consciousness|reflect|mirror|identity',
    },
]


def collect_traces(conn, trace_filter):
    """Sammelt Traces aus action_log fuer Training."""
    # Alle Aktionen der letzten 5 Tage die zum Filter passen
    rows = conn.execute(
        'SELECT action_type, module, input_summary, output_summary, duration_ms, success '
        'FROM action_log WHERE timestamp > datetime("now", "-5 days") '
        'AND (module LIKE ? OR input_summary LIKE ?)',
        ('%%%s%%' % trace_filter, '%%%s%%' % trace_filter)
    ).fetchall()
    return rows


def export_training_data(traces, model_info, output_path):
    """Exportiert Traces als JSONL Trainingsdaten."""
    training_data = []
    for t in traces:
        if t[3]:  # output_summary existiert
            training_data.append({
                'messages': [
                    {'role': 'system', 'content': model_info['description']},
                    {'role': 'user', 'content': t[2] or ''},
                    {'role': 'assistant', 'content': t[3]}
                ]
            })

    with open(output_path, 'w') as f:
        for item in training_data:
            f.write(json.dumps(item) + '\n')

    return len(training_data)


def trigger_desktop_training(model_info, data_path):
    """Startet Training auf Desktop WSL2 (Ubuntu 22.04 + YOUR_GPU) via SSH."""
    try:
        # 1. SCP Trainingsdaten zum Desktop (Windows-Seite)
        remote_data = 'C:/temp_training/%s.jsonl' % model_info['name']
        scp_cmd = ['scp', '-o', 'ConnectTimeout=10', data_path,
                    '%s:%s' % (DESKTOP_SSH, remote_data)]
        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.error('SCP fehlgeschlagen: %s', result.stderr)
            return False

        # 2. Daten in WSL2 kopieren
        wsl_data = '%s/training/%s.jsonl' % (DESKTOP_WSL_PROJECT, model_info['name'])
        copy_cmd = [
            'ssh', '-o', 'ConnectTimeout=10', DESKTOP_SSH,
            'wsl -d %s -- cp /mnt/c/temp_training/%s.jsonl %s' % (
                DESKTOP_WSL_DISTRO, model_info['name'], wsl_data)
        ]
        result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            log.warning('WSL copy warning: %s', result.stderr)

        # 3. Training in WSL2 starten (GPU via CUDA passthrough)
        train_script = (
            'cd %s && WAY2AGI_ROOT=%s '
            '/home/erik/.local/bin/python3 -m training.src.train_agent '
            '--agent %s --data %s --epochs 3 --lr 2e-4'
        ) % (DESKTOP_WSL_PROJECT, DESKTOP_WSL_PROJECT, model_info['name'], wsl_data)

        train_cmd = [
            'ssh', '-o', 'ConnectTimeout=10', DESKTOP_SSH,
            'wsl -d %s -- bash -c "%s"' % (DESKTOP_WSL_DISTRO, train_script)
        ]
        log.info('Starte WSL2 Training: %s auf %s', model_info['name'], DESKTOP_WSL_DISTRO)
        # Nicht-blockierend starten
        subprocess.Popen(train_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log.error('Desktop-Training Fehler: %s', e)
        return False


def main():
    log.info('=== Training Cronjob gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    for model_info in MODELS_TO_TRAIN:
        log.info('--- %s ---', model_info['name'])

        # 1. Traces sammeln
        traces = collect_traces(conn, model_info['trace_filter'])
        log.info('  %d Traces gefunden', len(traces))

        if len(traces) < 10:
            log.warning('  Zu wenig Traces (<10) fuer %s. Ueberspringe.', model_info['name'])
            continue

        # 2. Trainingsdaten exportieren
        output_path = os.path.join(TRACES_DIR, '%s-training-%s.jsonl' % (
            model_info['name'], datetime.datetime.now().strftime('%Y%m%d')
        ))
        count = export_training_data(traces, model_info, output_path)
        log.info('  %d Trainingsbeispiele exportiert -> %s', count, output_path)

        if count < 10:
            log.warning('  Zu wenig Beispiele (<10). Ueberspringe Training.')
            continue

        # 3. Training auf Desktop starten
        log.info('  Starte Training auf Desktop (YOUR_GPU)...')
        success = trigger_desktop_training(model_info, output_path)

        if success:
            log.info('  Training gestartet fuer %s', model_info['name'])
        else:
            log.error('  Training konnte nicht gestartet werden fuer %s', model_info['name'])

        # 4. Action Log
        conn.execute(
            'INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
            ('training_trigger', 'training', '%s: %d traces, %d examples' % (model_info['name'], len(traces), count),
             1 if success else 0, 'desktop')
        )
        conn.commit()

    conn.close()
    log.info('=== Training Cronjob beendet ===')


if __name__ == '__main__':
    main()
