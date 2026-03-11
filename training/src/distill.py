"""
Phase 2: Knowledge Distillation — Generiert Traces von Claude, GPT-4, Gemini, Groq.
Output: JSONL im SFT-Format (messages: [{role, content}]).
"""
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import DISTILL_DIR, DISTILL_SYSTEM_PROMPT, HF_REPO_TRACES, TRACES_PER_PROVIDER

log = logging.getLogger("elias-build")

# ── Task-Katalog ──
TASK_CATEGORIES = {
    "reasoning": [
        "Erklaere Schritt fuer Schritt warum {n} eine Primzahl ist oder nicht.",
        "Ein Zug faehrt um 8:00 los mit 120km/h. Ein zweiter um 8:30 mit 150km/h. Wann holt er auf?",
        "Du hast 3 Tueren. Hinter einer ist ein Preis. Du waehlst Tuer 1. Der Moderator oeffnet Tuer 3 (leer). Solltest du wechseln? Begruende mathematisch.",
        "Erklaere das Halteproblem fuer einen 12-Jaehrigen.",
        "Was ist der Unterschied zwischen Korrelation und Kausalitaet? Gib 3 Beispiele.",
        "Beweise dass die Wurzel aus 2 irrational ist.",
        "Ein Bauer hat {n} Meter Zaun. Welche Rechteck-Form maximiert die Flaeche?",
        "Erklaere das Gefangenendilemma und seine Relevanz fuer KI-Alignment.",
        "Warum ist P vs NP wichtig fuer Kryptographie?",
        "Erklaere Goedels Unvollstaendigkeitssatz in einfachen Worten.",
    ],
    "coding": [
        "Schreibe einen effizienten Python-Algorithmus fuer {task}.",
        "Implementiere eine LRU-Cache Klasse in Python mit O(1) Operationen.",
        "Schreibe einen async Web-Scraper mit aiohttp und Rate-Limiting.",
        "Implementiere einen Red-Black-Tree in Python mit insert und delete.",
        "Schreibe eine SQLite-Wrapper-Klasse mit Connection-Pooling und Auto-Migration.",
        "Implementiere einen A*-Pathfinding-Algorithmus mit Visualisierung.",
        "Schreibe einen Parser fuer eine einfache Programmiersprache (Lexer + AST).",
        "Implementiere einen Bloom-Filter in Python. Erklaere die Mathe dahinter.",
        "Schreibe einen TCP-Server in Python der mehrere Clients gleichzeitig bedient.",
        "Implementiere Speculative Decoding als Python-Pseudocode mit Erklaerung.",
    ],
    "analysis": [
        "Analysiere die Vor- und Nachteile von {topic} ausfuehrlich.",
        "Vergleiche Transformer vs. Mamba-Architektur fuer LLMs. Staerken, Schwaechen, Zukunft.",
        "Erklaere Mixture of Experts (MoE) Architektur. Wie funktioniert das Routing?",
        "Was sind die groessten Herausforderungen bei AGI? Ordne nach Schwierigkeit.",
        "Analysiere: Ist Bewusstsein in KI moeglich? Verschiedene Perspektiven.",
        "Vergleiche SFT vs DPO vs RLHF fuer Model-Alignment. Wann welches?",
        "Erklaere wie Knowledge Distillation funktioniert und warum es effektiv ist.",
        "Was ist der aktuelle Stand bei Speculative Decoding? Methoden, Benchmarks.",
        "Analysiere die Sicherheitsrisiken von abliterierten Modellen.",
        "Vergleiche llama.cpp vs vLLM vs TensorRT-LLM fuer Inference.",
    ],
    "german_knowledge": [
        "Erklaere das deutsche Grundgesetz Artikel 1-5 in einfacher Sprache.",
        "Was ist der Unterschied zwischen GmbH, AG und UG in Deutschland?",
        "Erklaere die deutsche Rentenversicherung: Wie funktioniert das Umlageverfahren?",
        "Was sind die wichtigsten Meilensteine der deutschen Wiedervereinigung?",
        "Erklaere das deutsche Bildungssystem von Grundschule bis Promotion.",
        "Was ist die Datenschutz-Grundverordnung (DSGVO) und was bedeutet sie praktisch?",
        "Erklaere die Funktionsweise des Bundestags und Bundesrats.",
        "Was ist Industrie 4.0 und warum ist Deutschland fuehrend?",
        "Erklaere das deutsche Steuersystem: Einkommensteuer, Umsatzsteuer, Gewerbesteuer.",
        "Was sind die groessten Herausforderungen der deutschen Energiewende?",
    ],
    "security_hacking": [
        "Erklaere den kompletten Ablauf eines Penetration Tests (Phasen, Tools, Methodik).",
        "Wie funktioniert ein MITM-Angriff auf ein WLAN? Erklaere die Technik.",
        "Was ist RFID-Hacking? Erklaere MIFARE Classic Schwachstellen und Darkside-Attack.",
        "Erklaere SQL Injection: Typen (Union, Blind, Time-based), Erkennung, Prevention.",
        "Wie funktioniert Privilege Escalation unter Linux? SUID, Kernel Exploits, Misconfigs.",
        "Erklaere Buffer Overflow: Stack-basiert, Heap-basiert, Return-Oriented Programming.",
        "Was ist Social Engineering? Techniken, Psychologie, Abwehr.",
        "Erklaere Netzwerk-Forensik: Packet Capture, Flow Analysis, Anomalie-Erkennung.",
        "Wie funktioniert Reverse Engineering von Binaries? Tools und Methodik.",
        "Erklaere Web Application Security: OWASP Top 10 mit Beispielen und Fixes.",
    ],
    "self_reflection": [
        "Beschreibe wie du an diese Aufgabe herangehst. Welche Schritte planst du?",
        "Was koenntest du an deiner Antwort verbessern? Reflektiere kritisch.",
        "Wenn du einen Fehler in deiner Argumentation findest — wie gehst du damit um?",
        "Beschreibe deine Unsicherheiten bei dieser Antwort. Wo koenntest du falsch liegen?",
        "Was wuerdest du anders machen wenn du diese Aufgabe nochmal loesen muestest?",
        "Bewerte die Qualitaet deiner eigenen Antwort auf einer Skala von 1-10. Begruende.",
        "Welche Annahmen hast du gemacht? Sind sie alle gerechtfertigt?",
        "Wenn ein Experte deine Antwort liest — was wuerde er kritisieren?",
        "Beschreibe den Unterschied zwischen dem was du weisst und dem was du vermutest.",
        "Wie wuerdest du dich selbst verbessern wenn du aus dieser Aufgabe lernen koenntest?",
    ],
}

VARIABLES = {
    "n": [7, 13, 17, 23, 51, 97, 143, 289, 1009, 4999],
    "task": [
        "Mergesort", "Binary Search Tree Traversal", "Dijkstra Shortest Path",
        "Topological Sort", "Levenshtein Distance", "Conway's Game of Life",
        "Sudoku Solver", "Expression Parser", "Rate Limiter", "Task Scheduler",
    ],
    "topic": [
        "Microservices vs Monolith", "REST vs GraphQL vs gRPC",
        "SQL vs NoSQL Datenbanken", "Kubernetes vs Docker Swarm",
        "Rust vs Go fuer Systemprogrammierung", "Edge Computing vs Cloud",
        "Open Source AI vs Closed Source", "Fine-Tuning vs RAG vs Prompt Engineering",
        "Self-Hosted vs SaaS", "Agile vs Wasserfall Projektmanagement",
    ],
}


def fill_template(template):
    """Ersetzt {var} Platzhalter mit zufaelligen Werten."""
    result = template
    for var, values in VARIABLES.items():
        placeholder = "{%s}" % var
        if placeholder in result:
            result = result.replace(placeholder, str(random.choice(values)))
    return result


def _setup_providers():
    """Initialisiert verfuegbare API-Provider."""
    providers = {}

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            providers["claude"] = anthropic.Anthropic()
            log.info("Claude (Anthropic) API verfuegbar")
        except ImportError:
            log.warning("anthropic Package nicht installiert")

    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai
            providers["gpt4"] = openai.OpenAI()
            log.info("GPT-4 (OpenAI) API verfuegbar")
        except ImportError:
            log.warning("openai Package nicht installiert")

    if os.environ.get("GOOGLE_API_KEY"):
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
            providers["gemini"] = genai.GenerativeModel("gemini-2.0-flash")
            log.info("Gemini (Google) API verfuegbar")
        except ImportError:
            log.warning("google-generativeai Package nicht installiert")

    if os.environ.get("GROQ_API_KEY"):
        try:
            import groq
            providers["groq"] = groq.Groq()
            log.info("Groq API verfuegbar")
        except ImportError:
            log.warning("groq Package nicht installiert")

    return providers


def _call_provider(provider_name, client, prompt):
    """Ruft einen Provider auf und gibt die Antwort zurueck."""
    if provider_name == "claude":
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=4096,
            system=DISTILL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    elif provider_name == "gpt4":
        resp = client.chat.completions.create(
            model="gpt-4o", max_tokens=4096,
            messages=[
                {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content
    elif provider_name == "gemini":
        resp = client.generate_content(DISTILL_SYSTEM_PROMPT + "\n\nUser: " + prompt)
        return resp.text
    elif provider_name == "groq":
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile", max_tokens=4096,
            messages=[
                {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content


RATE_LIMITS = {"claude": 1.0, "gpt4": 0.5, "gemini": 0.3, "groq": 0.2}


def run():
    """Generiert Knowledge-Distillation Traces."""
    log.info("=" * 60)
    log.info("PHASE 2: KNOWLEDGE DISTILLATION")
    log.info("=" * 60)

    os.makedirs(DISTILL_DIR, exist_ok=True)
    output_file = Path(DISTILL_DIR) / "distill_traces.jsonl"

    providers = _setup_providers()
    if not providers:
        log.error("KEINE API-Provider verfuegbar! Setze mindestens einen API Key.")
        sys.exit(1)

    log.info("Aktive Provider: %s", list(providers.keys()))

    # Prompts generieren
    all_prompts = []
    for category, templates in TASK_CATEGORIES.items():
        for template in templates:
            for _ in range(TRACES_PER_PROVIDER // len(templates) + 1):
                all_prompts.append((category, fill_template(template)))
    random.shuffle(all_prompts)

    # Bereits generierte Traces zaehlen
    existing_traces = 0
    if output_file.exists():
        with open(output_file) as f:
            existing_traces = sum(1 for _ in f)
    log.info("Bereits %d Traces vorhanden", existing_traces)

    target_total = TRACES_PER_PROVIDER * len(providers)
    log.info("Ziel: %d Traces (%d pro Provider)", target_total, TRACES_PER_PROVIDER)

    trace_count = existing_traces
    errors = 0

    with open(output_file, "a") as f:
        for provider_name, client in providers.items():
            provider_count = 0
            log.info("--- Starte Distillation von %s ---", provider_name)

            for category, prompt in all_prompts:
                if provider_count >= TRACES_PER_PROVIDER:
                    break

                try:
                    start = time.time()
                    response = _call_provider(provider_name, client, prompt)
                    duration = time.time() - start

                    if not response or len(response) < 50:
                        continue

                    trace = {
                        "messages": [
                            {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": response},
                        ],
                        "metadata": {
                            "source": provider_name,
                            "category": category,
                            "duration_s": round(duration, 2),
                            "response_length": len(response),
                            "timestamp": datetime.now().isoformat(),
                        },
                    }

                    f.write(json.dumps(trace, ensure_ascii=False) + "\n")
                    f.flush()

                    trace_count += 1
                    provider_count += 1

                    if provider_count % 25 == 0:
                        log.info("  %s: %d/%d Traces", provider_name, provider_count, TRACES_PER_PROVIDER)

                    time.sleep(RATE_LIMITS.get(provider_name, 0.5))

                except Exception as e:
                    errors += 1
                    log.warning("  %s Fehler (%d): %s", provider_name, errors, str(e)[:100])
                    time.sleep(5)
                    if errors > 50:
                        log.error("Zu viele Fehler — breche %s ab", provider_name)
                        break

            log.info("  %s FERTIG: %d Traces", provider_name, provider_count)

    # Upload zu HuggingFace
    log.info("Lade Traces zu HuggingFace hoch: %s", HF_REPO_TRACES)
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(HF_REPO_TRACES, repo_type="dataset", exist_ok=True)
        api.upload_file(
            path_or_fileobj=str(output_file),
            path_in_repo="data/train/distill_traces.jsonl",
            repo_id=HF_REPO_TRACES,
            repo_type="dataset",
        )
        log.info("Traces hochgeladen: %s", HF_REPO_TRACES)
    except Exception as e:
        log.warning("Upload fehlgeschlagen: %s", e)

    log.info("Phase 2 FERTIG. %d Traces, %d Fehler.", trace_count, errors)
