#!/usr/bin/env python3
"""Generate orchestrator training data via OpenAI API."""

import json
import urllib.request
import time
import sys

API_KEY = "os.environ.get("OPENAI_API_KEY", "")"
MODEL = "gpt-4o-mini"
OUTPUT = "/data/data/com.termux/files/home/repos/Way2AGI/training/artifacts/orchestrator-chatgpt.jsonl"
URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "Du bist der Way2AGI Orchestrator. Du verteilst Tasks optimal auf verfuegbare "
    "Compute-Nodes: Jetson Orin (64GB, 9 lokale Modelle, Always-On), Desktop YOUR_GPU "
    "(32GB VRAM, Heavy Compute), Zenbook (NPU, leichte Tasks), S24 (1.7B Modell, "
    "Verifikation). Plus Cloud: Groq (ultra-fast), OpenRouter (Step-Flash, Qwen-Coder), "
    "Grok (4.1). Routing-Regeln: Security->Desktop Abliterated, Code->Qwen-Coder, "
    "Reasoning->Step-Flash, Speed->Groq, Default->Nemotron. Du optimierst fuer Kosten, "
    "Latenz und Qualitaet. Antworte in Deutsch."
)

USER_PROMPTS = [
    # Task Routing (1-6)
    "Ich brauche eine Schwachstellenanalyse fuer ein Netzwerk mit 50 Hosts. Welchen Node nutzt du?",
    "Generiere mir Unit-Tests fuer eine Python FastAPI Anwendung mit 12 Endpunkten.",
    "Fasse mir dieses 200-seitige PDF zusammen und extrahiere die wichtigsten Punkte.",
    "Uebersetze diesen deutschen Text ins Englische, Franzoesische und Spanische gleichzeitig.",
    "Analysiere diesen Exploit-Code und erklaere ob er gefaehrlich ist.",
    "Schreibe einen Blogpost ueber KI-Trends 2026, ca. 2000 Woerter.",

    # Resource Allocation (7-11)
    "Der Desktop ist offline. Wie verteilst du Security-Tasks um?",
    "Alle Nodes sind ausgelastet zu 80%. Ein dringender Code-Review kommt rein. Was tust du?",
    "Ich habe 3 Tasks gleichzeitig: Code-Generierung, Textanalyse, und ein Quick-Check. Verteilung?",
    "Der Jetson hat nur noch 8GB RAM frei. Wie gehst du mit neuen Anfragen um?",
    "Wir haben Budget-Limit fuer Cloud-API erreicht. Nur lokale Ressourcen verfuegbar. Strategie?",

    # Model Selection (12-16)
    "Welches Modell waere am besten fuer Chain-of-Thought Reasoning ueber ein komplexes Matheproblem?",
    "Ich brauche ein Modell das Code reviewed UND Security-Aspekte prueft. Was empfiehlst du?",
    "Fuer eine einfache Textklassifikation — welches Modell und welcher Node?",
    "Ich will ein Fine-Tuning starten mit 500 Beispielen. Wo laeuft das am besten?",
    "Welches Modell eignet sich am besten fuer Echtzeit-Chat mit unter 500ms Latenz?",

    # Cost Optimization (17-20)
    "Vergleiche die Kosten: Groq vs OpenRouter vs lokal fuer 1000 Anfragen Code-Generierung.",
    "Wie kann ich die Cloud-Kosten um 50% senken ohne Qualitaetsverlust?",
    "Lohnt es sich den Desktop 24/7 laufen zu lassen oder nur on-demand zu starten?",
    "Berechne die optimale Verteilung fuer 100 taegliche Anfragen verschiedener Typen.",

    # Fallback Strategies (21-24)
    "Groq API gibt 429 Too Many Requests. Was ist der Fallback-Plan?",
    "Der Jetson ist nicht erreichbar und der Desktop schlaeft. Was tun bei einer dringenden Anfrage?",
    "Ein Modell auf dem Jetson gibt nur Muell aus. Wie reagierst du?",
    "Die Internet-Verbindung ist instabil. Wie sicherst du laufende Tasks ab?",

    # Load Balancing (25-27)
    "Es kommen 20 Anfragen gleichzeitig. Erstelle einen Verteilungsplan.",
    "Wie priorisierst du wenn the user eine Anfrage stellt vs ein automatischer Cron-Job?",
    "Beschreibe deinen Algorithmus fuer optimales Load Balancing ueber alle 4 Nodes.",

    # Multi-Node Coordination (28-29)
    "Ich will eine grosse Codebase analysieren. Wie teilst du die Arbeit auf mehrere Nodes auf?",
    "Koordiniere einen Multi-Step Workflow: Research -> Code -> Test -> Deploy ueber alle Nodes.",

    # Error Handling (30)
    "Ein Task ist nach 5 Minuten auf dem Desktop nicht fertig. Was sind deine Eskalationsstufen?",
]

def call_openai(user_prompt: str, retries: int = 3) -> str | None:
    """Call OpenAI API and return assistant response."""
    payload = json.dumps({
        "model": MODEL,
        "temperature": 0.8,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "Way2AGI/1.0",
    }

    req = urllib.request.Request(URL, data=payload, headers=headers, method="POST")

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"  HTTP {e.code}: {body[:200]}", file=sys.stderr)
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            elif e.code >= 500:
                time.sleep(2)
            else:
                return None
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            time.sleep(2)
    return None


def main():
    total = len(USER_PROMPTS)
    success = 0
    fail = 0

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for i, prompt in enumerate(USER_PROMPTS, 1):
            print(f"[{i}/{total}] {prompt[:60]}...")
            response = call_openai(prompt)
            if response:
                entry = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": response},
                    ]
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                success += 1
            else:
                print(f"  FAILED: {prompt[:40]}", file=sys.stderr)
                fail += 1
            # Small delay to avoid rate limits
            time.sleep(0.5)

    print(f"\nDone: {success}/{total} generated, {fail} failed")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
