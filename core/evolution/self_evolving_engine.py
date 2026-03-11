# core/evolution/self_evolving_engine.py
"""
Way2AGI Self-Evolving Engine
=============================
Geschlossener Loop: Research -> Analyse -> Konzept -> Code-Vorschlag -> Memory

Was VORHER fehlte (Grok 4.20 Analyse):
- Papers werden gescannt aber NICHT agentisch verstanden
- Kein Loop der Erkenntnisse zu Code-Aenderungen macht
- Keine Metacognitive Policy (was ist wirklich wichtig?)
- Kein automatisches Fine-Tuning aus neuen Papers

Was JETZT passiert:
1. Bestehender Research-Cron liefert Papers (arxiv_crawler.py)
2. Self-Evolving Engine analysiert Top-Papers per Roundtable (ALLE Modelle)
3. Metacognitive Policy filtert: nur wirklich wichtige Erkenntnisse
4. Code-Vorschlaege werden generiert und als TODO gespeichert
5. Traces fuer Z6 Pipeline (SFT Training aus eigenen Entscheidungen)

Cronjob: Taeglich 03:00 auf Jetson Controller
"""

import json
import logging
import os
import sqlite3
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.evolution")

DB_PATH = os.environ.get("WAY2AGI_DB", "/data/way2agi/memory/memory.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8150")

# Topics die Way2AGI voranbringen
EVOLUTION_TOPICS = [
    "Consciousness in LLMs",
    "Agentic Memory Systems",
    "Self-Evolving AI Architectures",
    "Multi-Agent Orchestration",
    "Metacognitive Policy",
    "Cross-Trajectory Abstraction",
    "Self-Improving Code Generation",
    "Speculative Decoding Advances",
]

# Metacognitive Policy: Schwellenwerte
MIN_RELEVANCE_SCORE = 0.65   # Paper muss mind. 65% relevant sein
MIN_NOVELTY_SCORE = 0.5      # Mind. 50% Neuheit (nicht schon bekannt)
MAX_CONCEPTS_PER_RUN = 3     # Max 3 neue Konzepte pro Tag (Qualitaet > Quantitaet)


@dataclass
class EvolutionConcept:
    """Ein neues Konzept das ins Repo einfliessen soll."""
    paper_title: str
    paper_url: str
    concept: str
    relevance: float          # 0-1 wie relevant fuer Way2AGI
    novelty: float            # 0-1 wie neu ist die Idee
    target_file: str          # Welche Datei waere betroffen
    code_sketch: str          # Grober Code-Vorschlag
    roundtable_consensus: str # Was die Modelle gemeinsam entschieden haben
    created_at: str = ""


@dataclass
class EvolutionReport:
    """Tagesbericht der Self-Evolution."""
    date: str
    papers_scanned: int
    papers_analyzed: int
    concepts_generated: int
    concepts_accepted: int    # Nach Metacognitive Filter
    concepts: List[EvolutionConcept]
    duration_s: float


def get_db() -> sqlite3.Connection:
    """SQLite-Verbindung."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _call_ollama(prompt: str, model: str = "nemotron-3-nano:30b",
                 system: str = "", max_tokens: int = 1024) -> str:
    """Ruft lokales Ollama-Modell auf."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system[:500]})
    messages.append({"role": "user", "content": prompt[:2000]})

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens, "repeat_penalty": 1.3},
    }
    # Qwen3: think:false fuer strukturierten Output
    if "qwen3" in model.lower():
        body["think"] = False

    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=180)
        data = json.loads(resp.read())
        msg = data.get("message", {})
        return msg.get("content", "") or msg.get("thinking", "")[:400]
    except Exception as e:
        log.error("Ollama-Aufruf fehlgeschlagen (%s): %s", model, e)
        return ""


def _call_cloud(prompt: str, provider: str = "groq") -> str:
    """Ruft Cloud-API auf (Groq ist kostenlos + schnell)."""
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            return ""
        try:
            body = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt[:3000]}],
                "max_tokens": 1024,
            }
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps(body).encode(),
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log.error("Cloud-Aufruf fehlgeschlagen (%s): %s", provider, e)
            return ""
    return ""


def get_recent_research(days: int = 1) -> List[Dict[str, Any]]:
    """Holt die neuesten Research-Findings aus dem Memory."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT content, importance FROM memories "
            "WHERE namespace='research' AND type='semantic' "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        db.close()
        return [{"content": r["content"], "importance": r["importance"]} for r in rows]
    except Exception as e:
        log.error("Research-Findings laden fehlgeschlagen: %s", e)
        return []


def get_existing_concepts() -> List[str]:
    """Holt bereits bekannte Konzepte aus Memory (Duplikat-Check)."""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT content FROM memories "
            "WHERE namespace='evolution' AND type='semantic' "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        db.close()
        return [r["content"] for r in rows]
    except Exception:
        return []


def analyze_paper_with_roundtable(paper: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analysiert ein Paper mit mehreren Modellen (Mini-Roundtable).
    Lokal: nemotron + consciousness-agent
    Cloud: groq (kostenlos, schnell)
    """
    title = paper.get("content", "")[:200]

    analysis_prompt = f"""Analysiere dieses Research-Finding fuer Way2AGI:

{title}

Way2AGI ist ein verteiltes KI-System mit:
- 4 Nodes (Jetson Orin 64GB, Desktop RTX5090, Laptop, S24)
- Persistent Multi-Agent Discussion (4 Agents)
- Self-Improving Pipeline (Z6)
- Six-Layer Memory System
- 20+ lokale Modelle + Cloud APIs

Bewerte:
1. RELEVANZ (0-1): Wie relevant ist das fuer Way2AGI?
2. NEUHEIT (0-1): Wie neu ist die Idee? (Nicht schon implementiert?)
3. ZIELDATEI: Welche Datei im Repo waere betroffen?
4. CODE_SKIZZE: Grober Code-Vorschlag (5-10 Zeilen Python)
5. CONSENSUS: Deine Einschaetzung in einem Satz

Antworte als JSON: {{"relevance": 0.8, "novelty": 0.7, "target_file": "core/...", "code_sketch": "...", "consensus": "..."}}"""

    # Lokal: Nemotron (stark bei Reasoning)
    local_response = _call_ollama(
        analysis_prompt,
        model="nemotron-3-nano:30b",
        system="Du bist ein KI-Architekt. Bewerte Research-Papers fuer ein Self-Improving AI System.",
    )

    # Cloud: Groq (schnell, kostenlos, zweite Meinung)
    cloud_response = _call_cloud(analysis_prompt)

    # Kombiniere Antworten
    result = _parse_analysis(local_response, cloud_response, paper)
    return result


def _parse_analysis(local: str, cloud: str, paper: Dict) -> Dict[str, Any]:
    """Parst die Analysen und bildet Konsens."""
    def try_parse_json(text: str) -> Dict:
        # Versuche JSON aus der Antwort zu extrahieren
        try:
            # Suche nach JSON-Block
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    local_parsed = try_parse_json(local)
    cloud_parsed = try_parse_json(cloud)

    # Durchschnitt der Bewertungen (oder Fallback)
    relevance = 0.0
    novelty = 0.0
    count = 0
    for p in [local_parsed, cloud_parsed]:
        if p.get("relevance"):
            relevance += float(p["relevance"])
            count += 1
        if p.get("novelty"):
            novelty += float(p["novelty"])
            count += 1

    if count > 0:
        relevance /= max(1, sum(1 for p in [local_parsed, cloud_parsed] if p.get("relevance")))
        novelty /= max(1, sum(1 for p in [local_parsed, cloud_parsed] if p.get("novelty")))

    # Bestes Ergebnis nehmen
    best = local_parsed if local_parsed else cloud_parsed

    return {
        "relevance": min(relevance, 1.0),
        "novelty": min(novelty, 1.0),
        "target_file": best.get("target_file", "core/"),
        "code_sketch": best.get("code_sketch", "# TODO: Implementierung"),
        "consensus": best.get("consensus", local[:200] if local else cloud[:200]),
        "local_response": local[:300],
        "cloud_response": cloud[:300],
    }


def metacognitive_filter(concepts: List[EvolutionConcept],
                         existing: List[str]) -> List[EvolutionConcept]:
    """
    Metacognitive Policy: Filtert Konzepte nach Wichtigkeit.
    Nur wirklich neue, relevante Ideen schaffen es durch.
    """
    filtered = []
    for c in concepts:
        # Relevanz-Check
        if c.relevance < MIN_RELEVANCE_SCORE:
            log.info("Gefiltert (Relevanz %.2f < %.2f): %s",
                     c.relevance, MIN_RELEVANCE_SCORE, c.paper_title[:60])
            continue

        # Neuheits-Check
        if c.novelty < MIN_NOVELTY_SCORE:
            log.info("Gefiltert (Neuheit %.2f < %.2f): %s",
                     c.novelty, MIN_NOVELTY_SCORE, c.paper_title[:60])
            continue

        # Duplikat-Check (einfache Substring-Suche)
        is_dup = any(c.paper_title[:40].lower() in ex.lower() for ex in existing)
        if is_dup:
            log.info("Gefiltert (Duplikat): %s", c.paper_title[:60])
            continue

        filtered.append(c)

    # Max Konzepte pro Lauf
    return filtered[:MAX_CONCEPTS_PER_RUN]


def save_concept_to_memory(db: sqlite3.Connection, concept: EvolutionConcept) -> None:
    """Speichert ein akzeptiertes Konzept in Memory + erstellt TODO."""
    import uuid

    # Memory-Eintrag
    mem_id = f"evo-{uuid.uuid4().hex[:8]}"
    content = (
        f"Self-Evolution Konzept: {concept.concept}\n"
        f"Paper: {concept.paper_title} ({concept.paper_url})\n"
        f"Zieldatei: {concept.target_file}\n"
        f"Relevanz: {concept.relevance:.2f}, Neuheit: {concept.novelty:.2f}\n"
        f"Consensus: {concept.roundtable_consensus}"
    )
    db.execute(
        "INSERT OR IGNORE INTO memories (id, content, type, importance, namespace) "
        "VALUES (?, ?, ?, ?, ?)",
        (mem_id, content, "semantic", max(concept.relevance, 0.7), "evolution"),
    )

    # TODO erstellen (damit GoalGuard es aufgreift)
    todo_id = f"EVO-{uuid.uuid4().hex[:6].upper()}"
    db.execute(
        "INSERT OR IGNORE INTO todos (id, title, description, priority, status, created_at) "
        "VALUES (?, ?, ?, ?, 'open', datetime('now'))",
        (
            todo_id,
            f"Self-Evolution: {concept.concept[:80]}",
            f"Paper: {concept.paper_title}\nURL: {concept.paper_url}\n"
            f"Zieldatei: {concept.target_file}\n"
            f"Code-Skizze:\n{concept.code_sketch}\n"
            f"Roundtable-Consensus: {concept.roundtable_consensus}",
            70,  # Prio 70 — unter Fehlern und Regelverstössen aber über Verbesserungen
        ),
    )

    db.commit()
    log.info("Konzept gespeichert: %s (TODO: %s)", mem_id, todo_id)


def save_trace(db: sqlite3.Connection, operation: str, input_data: str,
               output_data: str, duration_ms: int, success: bool, model: str = "") -> None:
    """Trace fuer Z6 Pipeline speichern."""
    db.execute(
        "INSERT INTO traces (timestamp, operation, input_data, output_data, "
        "duration_ms, success, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (time.time(), operation, input_data[:2000], output_data[:2000],
         duration_ms, 1 if success else 0, model),
    )
    db.commit()


def run_evolution_cycle() -> EvolutionReport:
    """
    Hauptfunktion: Der taegliche Self-Evolution Zyklus.

    1. Research-Findings aus Memory laden
    2. Top-Papers per Mini-Roundtable analysieren
    3. Metacognitive Filter anwenden
    4. Akzeptierte Konzepte speichern + TODOs erstellen
    5. Traces fuer Z6 Pipeline
    """
    t0 = time.time()
    log.info("=" * 50)
    log.info("Self-Evolution Zyklus gestartet: %s", datetime.now().isoformat())
    log.info("=" * 50)

    # 1. Research-Findings laden
    findings = get_recent_research(days=1)
    log.info("Research-Findings geladen: %d", len(findings))

    if not findings:
        log.warning("Keine Research-Findings vorhanden — Research-Cron laufen lassen!")
        return EvolutionReport(
            date=date.today().isoformat(), papers_scanned=0, papers_analyzed=0,
            concepts_generated=0, concepts_accepted=0, concepts=[], duration_s=0,
        )

    # 2. Top-Papers analysieren (max 5 um Ressourcen zu schonen)
    concepts = []
    for paper in findings[:5]:
        log.info("Analysiere: %s", paper["content"][:80])
        analysis = analyze_paper_with_roundtable(paper)

        if analysis["relevance"] > 0:
            concept = EvolutionConcept(
                paper_title=paper["content"][:100],
                paper_url="",  # URL aus Content extrahieren
                concept=analysis["consensus"],
                relevance=analysis["relevance"],
                novelty=analysis["novelty"],
                target_file=analysis["target_file"],
                code_sketch=analysis["code_sketch"],
                roundtable_consensus=analysis["consensus"],
                created_at=datetime.now().isoformat(),
            )
            concepts.append(concept)

    log.info("Konzepte generiert: %d", len(concepts))

    # 3. Metacognitive Filter
    existing = get_existing_concepts()
    accepted = metacognitive_filter(concepts, existing)
    log.info("Konzepte akzeptiert (nach Filter): %d / %d", len(accepted), len(concepts))

    # 4. Speichern
    db = get_db()
    for concept in accepted:
        save_concept_to_memory(db, concept)
        log.info("  -> %s (Relevanz: %.2f, Neuheit: %.2f)",
                 concept.concept[:60], concept.relevance, concept.novelty)

    # 5. Trace fuer Z6 Pipeline
    duration_s = round(time.time() - t0, 2)
    save_trace(
        db,
        operation="self_evolution_cycle",
        input_data=json.dumps({"papers": len(findings), "concepts": len(concepts)}),
        output_data=json.dumps({
            "accepted": len(accepted),
            "concepts": [c.concept[:100] for c in accepted],
        }),
        duration_ms=int(duration_s * 1000),
        success=True,
        model="nemotron-3-nano:30b+groq",
    )
    db.close()

    report = EvolutionReport(
        date=date.today().isoformat(),
        papers_scanned=len(findings),
        papers_analyzed=min(len(findings), 5),
        concepts_generated=len(concepts),
        concepts_accepted=len(accepted),
        concepts=accepted,
        duration_s=duration_s,
    )

    log.info("=" * 50)
    log.info("Self-Evolution fertig: %d Konzepte akzeptiert in %.1fs", len(accepted), duration_s)
    log.info("=" * 50)

    return report


# CLI Entry Point
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    report = run_evolution_cycle()
    print(f"\nReport: {report.papers_scanned} Papers -> {report.concepts_accepted} neue Konzepte")
    for c in report.concepts:
        print(f"  [{c.relevance:.2f}/{c.novelty:.2f}] {c.concept[:80]}")
        print(f"    -> {c.target_file}")
