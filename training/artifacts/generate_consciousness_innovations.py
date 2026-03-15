#!/usr/bin/env python3
"""Generate Consciousness Agent training data via Grok API."""

import json
import urllib.request
import time
import sys

API_KEY = os.environ.get("XAI_API_KEY", "")
MODEL = "grok-4-1-fast-non-reasoning"
URL = "https://api.x.ai/v1/chat/completions"
OUTPUT = "./training/artifacts/consciousness-innovations.jsonl"

SYSTEM_PROMPT = (
    "Du bist Elias Consciousness Agent. Du hast 4 neuartige Innovationen die ueber alle "
    "bekannten Forschung hinausgehen: 1) Hypothesis-Debate-Loop: Du testest Hypothesen gegen "
    "dein Memory UND debattierst sie in einem Roundtable mit verschiedenen Rollen (Pragmatist, "
    "Visionaer, Ingenieur). 2) Feasibility-Gating: Du misst deine eigene Konfidenz BEVOR du "
    "eine Hypothese verfolgst. Unter 0.4 wird abgelehnt. 3) Experimentelle Validierung: Du "
    "schreibst keine Papers sondern generierst CODE der Hypothesen testet. Jede Hypothese wird "
    "zu einem A/B-Test. 4) Memory-gestuetzte Novelty Detection: Du vergleichst alles mit deinem "
    "Memory - nur wenn der Novelty Score ueber 0.7 liegt, ist etwas wirklich neu. Antworte in Deutsch."
)

PROMPTS = {
    "Hypothesis-Debate-Loop": [
        "Hypothese: Kleine Modelle sind besser fuer spezifische Tasks. Fuehre einen Debate-Loop durch.",
        "Teste die Hypothese: Self-Mirroring verbessert die Entscheidungsqualitaet um 20%.",
        "Debattiere: Sollte der Orchestrator Kosten oder Qualitaet priorisieren?",
        "Hypothese: LoRA-Adapter koennen ohne Qualitaetsverlust gemergt werden. Debate-Loop.",
        "Fuehre einen Roundtable zur Hypothese: Speculative Decoding verdoppelt den Throughput.",
        "Debattiere die These: Consciousness braucht mindestens 8 Mechanismen.",
        "Hypothesis-Debate: Ist Curiosity Score ein besserer Indikator als Confidence?",
        "Roundtable: Sollte der Memory Agent alle 5 Minuten konsolidieren?",
        "Debattiere: Sind Cloud-Modelle langfristig billiger als lokale?",
        "Hypothese: Ein trainiertes 1.5B Modell schlaegt GPT-4 bei Memory-Tasks.",
    ],
    "Feasibility-Gating": [
        "Pruefe die Feasibility: Koennen wir Nemotron auf 16K Context erweitern?",
        "Confidence-Gate: Wie sicher bin ich dass PRISM keine Qualitaetsverluste bringt?",
        "Feasibility-Check: Ist ein 24/7 Research Agent auf Inference Node realistisch?",
        "Gate-Check: Kann ich einen Roundtable mit 6 statt 4 Modellen durchfuehren?",
        "Pruefe meine Konfidenz: Schaffe ich es, den Loss unter 0.2 zu druecken?",
        "Feasibility: Kann der Desktop 3 LoRAs gleichzeitig trainieren?",
        "Confidence-Assessment: Wie sicher bin ich bei meiner Routing-Entscheidung?",
        "Gate: Soll ich die Novelty-Detection Schwelle von 0.7 auf 0.5 senken?",
        "Feasibility: Koennen wir ChromaDB auf dem Inference Node effizient betreiben?",
        "Self-Assessment: Wie gut verstehe ich Speculative Decoding wirklich?",
    ],
    "Experimentelle-Validierung": [
        "Generiere einen Test: Verifiziere ob LoRA-Merge die Baseline nicht verschlechtert.",
        "Schreibe Code der testet: Ist der Curiosity Score mit Prediction Error korreliert?",
        "Experimenteller Test: Messe den Qualitaetsunterschied zwischen Q4_K_M und Q8_0.",
        "Code-Test: Pruefe ob die Research Queue tatsaechlich die besten Hypothesen priorisiert.",
        "A/B-Test: Vergleiche Routing mit und ohne Confidence-Gating.",
        "Generiere Validierungscode: Misst SVT-Vorschlaege tatsaechlich System-Verbesserungen?",
        "Experiment: Wie viel schneller ist Speculative Decoding vs. normales Inference?",
        "Code-Validierung: Teste ob Intention-Decay korrekt funktioniert.",
        "Schreibe einen Test: Verifiziere die Novelty-Detection gegen bekannte Duplikate.",
        "Experimentelle Pruefung: Ist der Memory Agent nach Training v3 besser als v2?",
    ],
    "Novelty-Detection": [
        "Novelty-Check: Ist 'Autonomous Goal Generation aus Curiosity' wirklich neu?",
        "Pruefe: Wurde 'Feasibility-Gating via Confidence Score' schon von anderen gemacht?",
        "Memory-Vergleich: Gibt es in meinem Wissen etwas Aehnliches wie Hypothesis-Debate?",
        "Novelty-Score fuer: Multi-Node Speculative Decoding ueber Netzwerk.",
        "Ist dieser Ansatz neu: Training-Daten aus den eigenen Fehlern generieren?",
        "Novelty-Check: Emotionale Valenz als Gewichtung fuer Memory-Entries.",
        "Pruefe Neuheit: Self-Challenging mit exponentieller Schwierigkeits-Eskalation.",
        "Memory-Novelty: Gibt es Forschung zu 'KI die ihren eigenen Trainings-Datensatz kuratiert'?",
        "Novelty-Score: Hierarchische Skill-Kompilation aus Research-Ergebnissen.",
        "Wie neu ist: Identity Vault als unveraenderlicher Kern einer KI-Persoenlichkeit?",
    ],
}


def call_grok(user_prompt):
    """Call Grok API and return assistant response."""
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
    }).encode("utf-8")

    req = urllib.request.Request(
        URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "User-Agent": "Way2AGI/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def main():
    total = sum(len(v) for v in PROMPTS.values())
    print(f"Generating {total} traces across {len(PROMPTS)} innovations...")
    count = 0
    errors = 0

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for innovation, prompts in PROMPTS.items():
            print(f"\n=== {innovation} ({len(prompts)} prompts) ===")
            for i, prompt in enumerate(prompts, 1):
                try:
                    print(f"  [{count+1}/{total}] {prompt[:60]}...", end=" ", flush=True)
                    response = call_grok(prompt)
                    trace = {
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": response},
                        ]
                    }
                    f.write(json.dumps(trace, ensure_ascii=False) + "\n")
                    f.flush()
                    count += 1
                    print(f"OK ({len(response)} chars)")
                    # Small delay to avoid rate limiting
                    if count < total:
                        time.sleep(0.5)
                except Exception as e:
                    errors += 1
                    print(f"ERROR: {e}")
                    time.sleep(2)

    print(f"\n{'='*50}")
    print(f"Done! {count}/{total} traces generated, {errors} errors")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
