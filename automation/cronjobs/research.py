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

DB_PATH = '/opt/way2agi/memory/db/elias_memory.db'
_DB_FALLBACKS = ['/opt/way2agi/memory/memory.db']
LOG_PATH = '/opt/way2agi/memory/logs/research.log'
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
        ('research_run', 'research', 'Queries: %d, Findings: %d' % (len(ARXIV_QUERIES), len(findings)), 1, 'inference-node')
    )
    conn.commit()




def get_robust_db():
    """Prevention: Versucht alle bekannten DB-Pfade. Erstellt Verzeichnisse falls noetig."""
    import os as _os
    for db_path in [DB_PATH] + _DB_FALLBACKS:
        try:
            _os.makedirs(_os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path, timeout=30)
            # Teste ob die DB die richtigen Tabellen hat
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if 'memories' in tables:
                log.info("DB verbunden: %s", db_path)
                return conn
            conn.close()
        except Exception as e:
            log.warning("DB %s nicht nutzbar: %s", db_path, e)
    raise RuntimeError("Keine nutzbare DB gefunden!")



GITHUB_QUERIES = [
    "ai memory system",
    "agent memory",
    "self-improving agent",
    "multi agent orchestration",
    "consciousness AI",
]

WAY2AGI_FEATURES = [
    "six-layer memory (episodic, semantic, procedural, protoself, identity, temporal)",
    "micro-orchestrator with bid-based routing",
    "consciousness agent with self-mirroring",
    "persistent multi-agent roundtable",
    "speculative decoding for inference",
    "self-improving pipeline (traces -> training -> deploy)",
    "distributed compute across 4 nodes",
]


def search_github_repos(query, max_results=5):
    """Search GitHub for repos matching query via API."""
    url = "https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=%d" % (
        urllib.request.quote(query), max_results
    )
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Way2AGI-Research/1.0"
        })
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        repos = []
        for item in data.get("items", []):
            repos.append({
                "name": item["full_name"],
                "description": (item.get("description") or "")[:200],
                "stars": item.get("stargazers_count", 0),
                "url": item.get("html_url", ""),
                "updated": (item.get("updated_at") or "")[:10],
                "topics": item.get("topics", []),
                "source": "github",
                "query": query,
            })
        return repos
    except Exception as e:
        log.error("GitHub search error (%s): %s", query, e)
        return []


def compare_repos_with_way2agi(repos):
    """Create a comparison summary of found repos vs Way2AGI features."""
    if not repos:
        return ""
    lines = ["GitHub Repo Comparison (vs Way2AGI features):"]
    for repo in repos[:10]:
        desc = repo["description"].lower()
        matching = []
        missing = []
        for feat in WAY2AGI_FEATURES:
            keywords = feat.split("(")[0].strip().lower().split()
            if any(kw in desc for kw in keywords if len(kw) > 3):
                matching.append(feat.split("(")[0].strip())
            else:
                missing.append(feat.split("(")[0].strip())
        lines.append(
            "- %s (%d stars): %s. Overlap: %s. Missing: %s" % (
                repo["name"], repo["stars"], repo["description"][:80],
                ", ".join(matching[:3]) if matching else "none",
                ", ".join(missing[:3]) if missing else "none"
            )
        )
    return "\n".join(lines)


def search_and_compare_github(conn):
    """Run GitHub search, compare with Way2AGI, save results."""
    all_repos = []
    seen_names = set()
    for query in GITHUB_QUERIES:
        repos = search_github_repos(query, max_results=3)
        log.info('  GitHub "%s": %d repos', query, len(repos))
        for r in repos:
            if r["name"] not in seen_names:
                seen_names.add(r["name"])
                all_repos.append(r)

    log.info("GitHub: %d unique repos gefunden", len(all_repos))

    if not all_repos:
        return

    # Compare with Way2AGI
    comparison = compare_repos_with_way2agi(all_repos)
    if comparison:
        log.info("Comparison:\n%s", comparison[:500])

    # Save each notable repo as semantic memory
    saved = 0
    for repo in all_repos[:10]:
        mem_id = "github-" + uuid.uuid4().hex[:8]
        content = (
            "GitHub Repo: %s (%d stars, updated %s). %s. URL: %s. Topics: %s" % (
                repo["name"], repo["stars"], repo["updated"],
                repo["description"][:200], repo["url"],
                ", ".join(repo.get("topics", [])[:5])
            )
        )
        conn.execute(
            "INSERT OR IGNORE INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)",
            (mem_id, content, "semantic", 0.5, "research")
        )
        saved += 1

    # Save comparison summary
    if comparison:
        comp_id = "github-comp-" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT OR IGNORE INTO memories (id, content, type, importance, namespace) VALUES (?, ?, ?, ?, ?)",
            (comp_id, comparison[:1000], "semantic", 0.7, "research")
        )

    conn.commit()
    log.info("%d GitHub repos + Comparison in Memory gespeichert", saved)


def main():
    log.info('=== Daily Research gestartet: %s ===', datetime.datetime.now().isoformat())
    conn = get_robust_db()

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

    # GitHub Repo Search + Comparison
    log.info('--- GitHub Repo Search ---')
    try:
        search_and_compare_github(conn)
    except Exception as e:
        log.error('GitHub search failed: %s', e)

    conn.close()
    log.info('=== Daily Research beendet ===')


if __name__ == '__main__':
    main()
