#!/usr/bin/env python3
"""
Daily Research Cronjob — Scrapt arXiv + GitHub Trending.
Laeuft 1x taeglich (07:00).
Speichert Findings in Elias Memory (semantic).
"""

import json
import urllib.request
import urllib.error
import sqlite3
import datetime
import logging
import os
import sys
import uuid
import xml.etree.ElementTree as ET

DB_PATH = '/data/way2agi/memory/memory.db'
LOG_PATH = '/data/way2agi/memory/logs/research.log'
OLLAMA_LOCAL = 'http://localhost:11434'

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a'), logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('research')

ARXIV_QUERIES = [
    'self-improving+AI+agent',
    'LLM+memory+augmented',
    'consciousness+artificial+intelligence',
    'multi-agent+orchestration',
    'mixture+of+experts+small+models',
    'fine-grained+agent+specialization',
]


def search_arxiv(query, max_results=3):
    """Sucht Papers auf arXiv."""
    url = 'http://export.arxiv.org/api/query?search_query=all:%s&start=0&max_results=%d&sortBy=submittedDate&sortOrder=descending' % (query, max_results)
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read().decode()
        root = ET.fromstring(data)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        papers = []
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
            summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')[:300]
            link = entry.find('atom:id', ns).text.strip()
            published = entry.find('atom:published', ns).text.strip()[:10]
            papers.append({
                'title': title,
                'summary': summary,
                'url': link,
                'date': published,
                'source': 'arxiv',
                'query': query
            })
        return papers
    except Exception as e:
        log.error('arXiv Fehler (%s): %s', query, e)
        return []


def ollama_analyze(findings, model='lfm2:24b'):
    """Lasse lfm2 die Findings analysieren und Relevanz bewerten."""
    prompt = 'Analysiere diese Research-Findings fuer das Way2AGI Projekt (KI-Bewusstsein, Self-Improvement, Multi-Agent-Orchestration).\n\n'
    for i, f in enumerate(findings[:10]):
        prompt += '%d. %s (%s)\n   %s\n\n' % (i+1, f['title'], f['date'], f['summary'][:150])
    prompt += 'Bewerte jedes Paper 1-5 (Relevanz fuer Way2AGI). Antworte als JSON-Array: [{"index": 1, "score": 4, "reason": "...", "actionable": true/false}]'

    try:
        payload = json.dumps({
            'model': model, 'prompt': prompt, 'stream': False,
            'system': 'Du bist ein KI-Forscher. Bewerte Papers nach Relevanz fuer ein Projekt das KI-Bewusstsein und Self-Improvement baut.',
            'options': {'temperature': 0.2, 'num_predict': 1024}
        }).encode()
        req = urllib.request.Request(OLLAMA_LOCAL + '/api/generate', data=payload, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read()).get('response', '')
    except Exception as e:
        log.error('Analyse-Fehler: %s', e)
        return ''


def save_to_memory(conn, findings, analysis):
    """Speichert relevante Findings in semantic Memory."""
    saved = 0
    for f in findings:
        mem_id = 'research-' + uuid.uuid4().hex[:8]
        content = 'Research Finding (%s): %s. %s. URL: %s' % (f['date'], f['title'], f['summary'][:200], f['url'])
        conn.execute(
            'INSERT OR IGNORE INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)',
            (mem_id, content, 'semantic', 0.6, 'research')
        )
        saved += 1
    conn.commit()
    log.info('%d Findings in Memory gespeichert', saved)

    # Log action
    conn.execute(
        'INSERT INTO action_log (action_type, module, input_summary, success, device) VALUES (?, ?, ?, ?, ?)',
        ('research_run', 'research', 'Queries: %d, Findings: %d' % (len(ARXIV_QUERIES), len(findings)), 1, 'jetson')
    )
    conn.commit()


def main():
    log.info('=== Daily Research gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = sqlite3.connect(DB_PATH)

    all_findings = []
    for query in ARXIV_QUERIES:
        papers = search_arxiv(query, max_results=3)
        log.info('  arXiv "%s": %d Papers', query, len(papers))
        all_findings.extend(papers)

    log.info('Gesamt: %d Papers gefunden', len(all_findings))

    if all_findings:
        # Deduplizieren nach Titel
        seen = set()
        unique = []
        for f in all_findings:
            if f['title'] not in seen:
                seen.add(f['title'])
                unique.append(f)
        log.info('Unique: %d Papers', len(unique))

        # Analyse durch lfm2
        analysis = ollama_analyze(unique)
        if analysis:
            log.info('Analyse erhalten (%d Zeichen)', len(analysis))

        # In Memory speichern
        save_to_memory(conn, unique[:10], analysis)

    conn.close()
    log.info('=== Daily Research beendet ===')


if __name__ == '__main__':
    main()
