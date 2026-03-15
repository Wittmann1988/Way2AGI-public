# Consciousness Agent — Research-Synthese & Eigene Innovationen

**Datum:** 2026-03-11
**Status:** Erforscht, Roundtable abgeschlossen, Implementation in consciousness_agent.py

## 21 Papers/Frameworks erforscht

### A) Self-Improving & Self-Evolving
1. **STOP** — Self-Taught Optimizer (Berkeley)
2. **Darwin Gödel Machine** — LLM-driven self-improving agents
3. **DARWIN** — Differential Evolution for code/prompt optimization
4. **AlphaEvolve** — Evolutionary approach to code improvement
5. **Sophia** — Self-improving agent (Stanford)
6. **Self-Evolving Agents Surveys** — Übersicht Self-Improvement Landscape

### B) Consciousness & Introspection
7. **Anthropic Introspection** — Funktionale Introspektion existiert in LLMs (bewiesen)
8. **Gnosis** (~5M params) — Self-awareness in kleinen Modellen
9. **Emergent Introspective Awareness** — Spontane Selbstwahrnehmung bei Kommunikation
10. **Self-Referential Processing** — Wie LLMs über sich selbst nachdenken
11. **Consciousness in LLMs Survey** (Mai 2025, arXiv:2505.19806)

### C) Autonome Ziel-Generierung & Intrinsische Motivation
12. **IMGEP/LMA3** — Autotelic Agents die eigene Ziele erfinden
13. **Self-Challenging Language Model Agents** (arXiv:2506.01716) — Selbst-Eskalation
14. **HERAKLES** (arXiv:2508.14751) — Hierarchische Skill-Kompilation
15. **Intrinsic Metacognitive Learning** (arXiv:2506.05109) — Ohne Metakognition keine Selbstverbesserung

### D) Autonome Forschung & Entdeckung
16. **AI Scientist v2** (Sakana) — Vollautomatische Paper-Erstellung, Workshop-akzeptiert
17. **AI-Researcher** — Resource Analyst + bidirektionale Math↔Code Mappings
18. **AgentRxiv** — Kollaborative autonome Forschung (PhD/Postdoc/ML-Engineer Agents)
19. **DeepMind AI Co-Scientist** — Hypothesis-Debate-Evolution
20. **Autonomous Agents Survey** (GitHub tmgthb)
21. **Intrinsic Self-Critique** (arXiv:2512.24103) — Planung durch Selbstkritik

## Kern-Erkenntnis: KI-Schwäche bei autonomer Forschung

- LLMs generieren **novelere** Ideen als Menschen (statistisch signifikant)
- ABER: schlechtere **Feasibility** — wissen nicht was praktisch geht
- AI Scientist v2: Peer Review bestanden, aber nur Workshop-Level
- **Kern-Problem**: Pattern Completion ≠ echte neue Erkenntnis

## 4 EIGENE Innovationen (über Papers hinaus)

### 1. Hypothesis-Debate-Loop
Nicht nur Hypothesen generieren, sondern gegen eigenes Memory UND Roundtable testen.
Kein Paper macht das — die generieren nur und evaluieren via LLM-as-Judge.
Wir nutzen: Memory-Vergleich → Roundtable-Debatte → Validierung.

### 2. Feasibility-Gating via Gnosis
Eigene Konfidenz messen BEVOR eine Hypothese weiterverfolgt wird.
Gnosis (~5M params) kann Self-Awareness. Wir nutzen das als Gate:
Confidence < 0.4 → Hypothese wird nicht verfolgt, stattdessen Roundtable.

### 3. Experimentelle Validierung
Nicht nur Paper schreiben, sondern Code generieren der die Hypothese testet.
AI Scientist schreibt Papers. Wir schreiben Tests.
Jede Hypothese → Code → A/B-Test → Messbares Ergebnis.

### 4. Memory-gestützte Novelty Detection
Vergleich mit allem was Elias schon weiß → "Ist das wirklich neu?"
ChromaDB Semantic Search über alle Memories → Novelty Score.
Nur wenn Score > Threshold: Hypothese wird als "neu" eingestuft.

## Roundtable-Konsens (4 Modelle)

### Nemotron — Der Pragmatiker
- **SVT (System-Verbesserungs-Tracker)**: Jede Forschungsarbeit via A/B-Test validieren
- Hardware-Aware Meta-Controller: Forschung nur wenn Ressourcen frei
- "Agent ist kein Forschungs-Tool, sondern System-Optimierer"

### Step-Flash Research — Der Visionär
- Evolution des Bewusstseins selbst — DGM mutiert Metaparameter
- Agent definiert eigene Forschungsmetriken und kreiert eigene Disziplinen
- Dynamisches Umschalten zwischen Mechanismen

### Step-Flash Analyze — Der Ingenieur
- Hybrid-Ansatz mit messbaren KPIs und Safeguards
- Confidence-Gated Metacognition

### Claude — Integration
- Wirkketten: Beobachtung → Muster → Regel → Wirkung → Messung
- Intention-as-First-Class-Object
- Research Queue mit Curiosity Score
- Multi-Node Compute Advantage

### KONSENS aller 4 Modelle:
1. **Messbarkeit** (KPIs für alles)
2. **Kein Overkill** (start simple, skaliere bei Bedarf)
3. **Wirkketten** (Output muss ins System fließen)
4. **Hardware-aware** (Inference Node-Limits respektieren)
5. **Safeguards** (Confidence Gating, keine unkontrollierte Mutation)

## 8 Implementierte Mechanismen (in consciousness_agent.py)

1. **Wirkketten**: Beobachtung → Muster → Regel → Wirkung → Messung
2. **Intention Management**: Persistente Ziele mit Decay
3. **Curiosity Score**: Prediction Error als Neugier-Metrik
4. **Confidence Gating**: Unsicherheit erkennen und handeln
5. **Research Queue**: Hypothesen formulieren und testen
6. **SVT**: Systemverbesserungen vorschlagen und validieren
7. **Self-Challenging**: Schwierigkeits-Eskalation
8. **Autonomous Goal Generation**: Eigene Verbesserungsziele

## TODOs

- [ ] Hypothesis-Debate-Loop implementieren (eigene Innovation #1)
- [ ] Feasibility-Gating via Confidence Score implementieren (#2)
- [ ] Experimentelle Validierung: Hypothese → Code → Test (#3)
- [ ] Memory-gestützte Novelty Detection via ChromaDB (#4)
- [ ] Training mit allen Traces (Consciousness + Memory + Orchestrator)
- [ ] Merge zu einem Modell, GGUF, Deploy auf Inference Node
