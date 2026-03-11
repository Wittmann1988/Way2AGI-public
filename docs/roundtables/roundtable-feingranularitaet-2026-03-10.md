# Roundtable: Feingranularitaet im Multi-Agent-System
**Datum:** 2026-03-10
**Teilnehmer:** Nemotron-3-Nano 30B, Step-3.5-Flash (Reasoning), Kimi-K2 (Groq), Qwen-Coder (Fallback Nemotron), Step-Flash Analyse
**Koordinator:** Claude Opus 4.6 (Elias)

---

## Ausgangslage

**Research-Ergebnis (Nemotron):**
- 1-Task-Agenten schlagen 7B-Generalisten um ~12% bei 30% weniger Latenz
- Optimaler Punkt: 2-3 Agenten pro Pipeline, darueber diminishing returns
- Merge-Regel: Nur zusammenlegen wenn Tasks >80% sequentiell UND gemeinsamer Kontext
- Spezialisierte 2B Modelle erreichen ~90% der Performance von 7B Generalisten bei 3-5x weniger Kosten

**Hardware:**
- Jetson Nano (.21): lfm2:24b, smallthinker:1.8b, nemotron-3-nano:30b
- Desktop YOUR_GPU (.129): lfm2:24b, step-3.5-flash, qwen3.5:9b, abliterated Modelle
- Zenbook (.111): lfm2:24b, smallthinker:1.8b, qwen3:1.7b
- S24 Tablet (.182): qwen3:1.7b (begrenzt)
- Cloud: Gemini, Groq, OpenAI, OpenRouter

---

## KONSENS: Zusammenfassung aller Modelle

### 1. Tasks pro Agent: 1 Task ist optimal (EINSTIMMIG)

Alle 5 Perspektiven sind sich einig:
- **1 Task pro Agent** ist der Standard fuer maximale Spezialisierung
- **2 Tasks** nur wenn >80% sequentiell UND gemeinsamer Kontext
- **3+ Tasks** vermeiden (diminishing returns, Kontext-Switch-Overhead)
- Die 12% Performance-Gewinn gegenueber 7B kommen NUR durch strikte Spezialisierung

**Step-Flash Nuance (Ansatz B):** Statt einzelne Tasks sollten wir in **Task-Clustern** denken (2-3 verwandte Tasks pro Cluster). Das reduziert Orchestrierungs-Overhead bei 10+ Agenten erheblich.

### 2. Micro-Agent-Katalog (KONSENS: 10 Kern-Agenten)

Aus allen Vorschlaegen destilliert, priorisiert nach unserem Way2AGI Use-Case:

| # | Agent-Name | Aufgabe | Basis-Modell | Geraet | Prioritaet |
|---|-----------|---------|-------------|--------|-----------|
| 1 | **IntentRouter** | Intent-Klassifikation (Routing-Entscheidung) | qwen3:1.7b (SFT) | S24 Tablet / Zenbook | P0 - Kritisch |
| 2 | **CodeGen** | Python/JS Code-Generierung | smallthinker:1.8b (SFT) | Zenbook (.111) | P0 - Kritisch |
| 3 | **CodeReview** | Code-Review, Bug-Findung, Security-Scan | qwen3.5:9b / step-flash | Desktop RTX (.129) | P0 - Kritisch |
| 4 | **Summarizer** | Text-Zusammenfassung (kurz + lang) | smallthinker:1.8b (SFT) | Jetson Nano (.21) | P1 - Wichtig |
| 5 | **EntityExtractor** | NER: Namen, Orte, Konzepte extrahieren | smallthinker:1.8b (SFT) | Jetson Nano (.21) | P1 - Wichtig |
| 6 | **FactChecker** | Fakten-Pruefung gegen Knowledge-Base | smallthinker:1.8b (SFT) | Jetson Nano (.21) | P1 - Wichtig |
| 7 | **DataTransformer** | JSON/CSV/Strukturierte Daten-Konvertierung | qwen3:1.7b (SFT) | Zenbook (.111) | P1 - Wichtig |
| 8 | **GrammarPolisher** | Deutsche Grammatik/Rechtschreibung korrigieren | qwen3:1.7b (SFT) | S24 Tablet (.182) | P2 - Spaeter |
| 9 | **SentimentAnalyzer** | Sentiment-Klassifikation (5 Klassen) | qwen3:1.7b (SFT) | S24 Tablet (.182) | P2 - Spaeter |
| 10 | **TestGen** | Unit-Test-Generierung (pytest/Jest) | smallthinker:1.8b (SFT) | Jetson Nano (.21) | P2 - Spaeter |

**Geraete-Verteilung:**
- **Jetson Nano (.21):** 3 Agenten (Summarizer, EntityExtractor, FactChecker) - leichte, asynchrone Tasks
- **Desktop RTX (.129):** 1 Agent (CodeReview) + Training-Server + Fallback fuer komplexe Tasks
- **Zenbook (.111):** 2 Agenten (CodeGen, DataTransformer) - mittlere Latenz-Anforderung
- **S24 Tablet (.182):** 2-3 Agenten (IntentRouter, GrammarPolisher, SentimentAnalyzer) - leichte Klassifikation
- **Cloud:** Fallback fuer alle Agenten bei Ueberlastung oder Praezisions-Anforderung >95%

### 3. Training spezialisierter 1.5-2B Modelle (KONSENS)

**Methode: LoRA/QLoRA auf YOUR_GPU (EINSTIMMIG)**

| Aspekt | Empfehlung | Konsens-Staerke |
|--------|-----------|----------------|
| **Basis-Modelle** | smallthinker:1.8b + qwen3:1.7b | Einstimmig |
| **Technik** | LoRA (r=8-16, alpha=16-64) mit QLoRA (4-bit) | Einstimmig |
| **Daten pro Agent** | 5k-50k hochwertige Beispiele | Konsens (Spanne variiert) |
| **Daten-Quelle** | Knowledge Distillation von 7B+ Teacher-Modellen | Starker Konsens |
| **Training-Dauer** | 2-4 Stunden pro Agent auf YOUR_GPU | Konsens |
| **Quantisierung** | INT4/INT8 fuer Edge-Deployment | Einstimmig |
| **Evaluation** | Task-spezifische Metriken + General-Intelligence Check (<5% Drop) | Starker Konsens |

**Konkrete Training-Pipeline:**
```
1. Teacher-Modell (lfm2:24b oder qwen3.5:9b) generiert synthetische Daten
2. Daten filtern: Nur Confidence >0.9 behalten
3. Manuell kuratieren: Top-10k Beispiele pro Agent verifizieren
4. LoRA Fine-Tuning auf YOUR_GPU (r=8, alpha=16, 3 Epochen, LR=2e-4)
5. Quantization-Aware Training fuer Edge-Modelle
6. Export: GGUF/ONNX/TensorRT je nach Ziel-Hardware
7. Evaluation: Task-Accuracy + Latenz-Benchmark auf Ziel-Geraet
```

### 4. Routing-Strategie (KONSENS)

**Phase 1: Regelbasiert (EINSTIMMIG als Start)**

```
Routing-Entscheidungsbaum:
1. IntentRouter klassifiziert Anfrage (auf S24/Zenbook, <50ms)
2. Task-Typ bestimmt Agent-Zuordnung (Keyword + Intent)
3. Hardware-Check: Ist Ziel-Geraet verfuegbar und unter 85% Last?
4. Latenz-Budget: Echtzeit (<100ms) = Edge, Tolerant (>500ms) = Cloud erlaubt
5. Fallback-Kaskade: Primaer-Agent → Alternatives Geraet → Cloud
```

**Phase 2: ML-basierter Router (SPAETER)**
- Mini-Classifier (TinyBERT ~100M) lernt aus Routing-Traces
- Dynamische Gewichtung: Task-Typ (45%), Kontext-Laenge (25%), Geraete-Load (15%), Latenz-Budget (10%), Kosten (5%)

**Alle Modelle betonen:**
- Routing-Overhead darf nicht >10% der Gesamt-Latenz sein
- Jeder Agent MUSS einen Cloud-Fallback haben
- Health-Monitoring pro Geraet ist Voraussetzung

### 5. Implementierungsplan (KONSENS: 4 Phasen, 8 Wochen)

#### Phase 1: Infrastruktur + Core-Agents (Woche 1-2)
- [ ] Agent-Registry mit Health-Checks fuer alle 4 Geraete
- [ ] Basis-Kommunikation (gRPC oder REST) zwischen Geraeten
- [ ] Regelbasierter Router implementieren (Keyword-Matching)
- [ ] 3 P0-Agenten deployen: IntentRouter, CodeGen, CodeReview
- [ ] Einfaches Monitoring (Latenz, Fehlerrate pro Agent)

#### Phase 2: SFT-Training + Erweiterung (Woche 3-4)
- [ ] Synthetische Trainingsdaten generieren (Teacher: lfm2:24b)
- [ ] LoRA-Training fuer IntentRouter, CodeGen, Summarizer auf YOUR_GPU
- [ ] Quantisierung fuer Edge-Deployment (INT4/INT8)
- [ ] 3 P1-Agenten hinzufuegen: Summarizer, EntityExtractor, DataTransformer
- [ ] Performance-Benchmarking: Latenz + Accuracy pro Agent

#### Phase 3: Pipeline-Integration + Cloud-Fallback (Woche 5-6)
- [ ] Multi-Agent-Pipelines bauen (z.B. Intent → CodeGen → TestGen)
- [ ] Cloud-Fallback fuer alle Agenten konfigurieren
- [ ] Caching-Layer (Redis) fuer wiederholte Anfragen
- [ ] Load-Balancing zwischen Geraeten
- [ ] P2-Agenten hinzufuegen: FactChecker, GrammarPolisher, SentimentAnalyzer

#### Phase 4: Optimierung + Monitoring (Woche 7-8)
- [ ] OpenTelemetry/Prometheus + Grafana Dashboard
- [ ] A/B-Testing Framework fuer Agent-Versionen
- [ ] Router auf ML-basiert umstellen (wenn genuegend Traces)
- [ ] Merge-Regel testen: Welche Agenten profitieren von Zusammenlegung?
- [ ] Cost-Tracking pro Request
- [ ] Canary-Deployments fuer neue Modell-Versionen

---

## Blinde Flecken / Warnungen (aus Step-Flash Analyse)

1. **Orchestrierungs-Overhead:** Bei 10+ Agenten kann Routing 30% der Gesamt-Latenz ausmachen. Router auf staerkstem Edge-Geraet (Desktop/Zenbook) platzieren.

2. **Task-Grenzfaelle:** "Fasse diesen Code zusammen" - ist das Summarizer oder CodeReview? Starten mit KEINEM Merge, nur fuer manuell definierte Patterns hinzufuegen.

3. **Datenqualitaet entscheidend:** Manuelle Kuratierung der Top-10k Beispiele pro Agent ist unerlaeasslich. Verunreinigte Daten ruinieren Spezialisierung.

4. **Jetson Nano Limitierung:** ~1-2 Token/s fuer 2B Modelle. Nur fuer asynchrone, nicht-echtzeit Tasks geeignet. Haupt-Agenten auf Desktop/Cloud.

5. **Monitoring von Anfang an:** Ohne zentrale Logs, Metriken und Tracing wird das System bei 10+ Agenten zur Blackbox. OpenTelemetry ab Tag 1.

---

## Abweichende Meinungen

| Thema | Mehrheit | Abweichung |
|-------|---------|-----------|
| Agent-Anzahl | 10-12 spezialisierte Agents | Step-Flash: Lieber 4-5 Task-Cluster statt 10+ Einzel-Agents |
| Daten-Menge | 5k-50k pro Agent | Kimi-K2: 50k, Nemotron: 50-100k, Step-Flash: 5-20k (Qualitaet > Quantitaet) |
| Router-Komplexitaet | Regelbasiert als Start | Qwen-Coder/Nemotron2: Sofort Embedding-basiert (Sentence-BERT) |
| Timeline | 8 Wochen MVP | Step-Flash Analyse: 6-9 Monate realistisch fuer Produktion |

---

## Entscheidungen fuer Way2AGI

Basierend auf dem Konsens empfehle ich:

1. **Ansatz B (Task-Cluster)** statt reiner 1-Task-Agents - reduziert Orchestrierungs-Komplexitaet
2. **Start mit 3 P0-Agenten** (IntentRouter, CodeGen, CodeReview) in Woche 1-2
3. **LoRA-Training auf YOUR_GPU** mit Knowledge-Distillation von lfm2:24b als Teacher
4. **Regelbasierter Router** als Start, ML-basiert erst wenn genuegend Traces gesammelt
5. **10k hochwertige Beispiele** pro Agent (Qualitaet vor Quantitaet)
6. **OpenTelemetry von Tag 1** - kein nachtraegliches Monitoring

---

*Naechster Schritt: Phase 1 starten - Agent-Registry + Health-Checks + 3 Core-Agents deployen*
