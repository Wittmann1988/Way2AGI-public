# Grok Prompt: Way2AGI Orchestrator Redesign — Micro-Orchestrator Architecture

## Kontext

Wir bauen Way2AGI — ein selbstverbesserndes Multi-Node KI-System. Aktuell haben wir einen **zentralen Orchestrator** auf dem Jetson Orin der alle Tasks routet. Das Problem: Single Point of Failure, und der zentrale Server muss alle Modelle auf allen Nodes kennen.

## Aktuelle Architektur (was wir haben)

```
                    ┌─────────────────────┐
                    │  Jetson Orin 64GB    │
                    │  Orchestrator v2.0   │
                    │  Port 8150           │
                    │  19 Modelle lokal    │
                    └─────────┬───────────┘
                              │
            ┌─────────────────┼──────────────────┐
            │                 │                  │
   ┌────────▼────────┐ ┌─────▼──────┐  ┌───────▼───────┐
   │ Desktop RTX5090 │ │ Zenbook    │  │ S24 Ultra     │
   │ 22 Modelle      │ │ 4 Modelle  │  │ qwen3.5:0.8b  │
   │ Port 8100       │ │ Port 8150  │  │ Port 8200     │
   └─────────────────┘ └────────────┘  └───────────────┘
```

### Probleme
1. Jetson muss ALLE Modelle auf ALLEN Nodes kennen
2. Routing-Logik ist hardcoded (model_map dict)
3. Wenn Jetson offline → ganzes System tot
4. Einfache Tasks werden an zu grosse Modelle geroutet
5. Keine echte dezentrale Entscheidungsfindung

## Eriks Vision: Micro-Orchestrator pro Geraet

Jedes Geraet bekommt seinen eigenen **lokalen Mini-Orchestrator** (qwen3.5:0.8b, nur 1 GB RAM). Dieser entscheidet selbststaendig:
- Welches lokale Modell fuer den Task am besten ist
- Ob der Task lokal ausfuehrbar ist oder weitergeleitet werden muss
- Eigene Health-Checks, eigenes Model-Registry

Der **zentrale Orchestrator** (Jetson) spricht dann nur noch die Geraete-Orchestratoren an, nicht mehr direkt die Modelle.

## Deine Aufgabe

Designe die neue Architektur. Ich brauche:

### 1. Micro-Orchestrator Spezifikation
- Was macht der lokale Mini-Orchestrator auf jedem Geraet?
- Welches Modell? (qwen3.5:0.8b oder eigenes trainiertes?)
- API-Endpunkte pro Geraet
- Wie entscheidet er lokal vs. weiterleiten?
- Wie registriert er sich beim zentralen Orchestrator?

### 2. Zentral-Orchestrator Redesign
- Wie aendert sich die zentrale Logik?
- Statt model_map → device_capabilities Registry
- Load-Balancing ueber Geraete-Orchestratoren
- Redundanz: Was wenn Jetson offline geht?

### 3. Communication Protocol
- Wie kommunizieren die Orchestratoren untereinander?
- REST? WebSocket? gRPC? Message Queue?
- Heartbeat / Service Discovery
- Task-Delegation Protokoll

### 4. Speculative Decoding Integration
- Wir haben: Nemotron-30B + Nemotron-4B-Draft auf Jetson (31 tok/s)
- Wie integriert sich das in die neue Architektur?
- Kann der Desktop sein eigenes SpecDec-Paar haben?

### 5. Cloud-Integration
- Nemotron-3-Super:120b (Ollama Cloud) als permanentes Modell
- GPT-5.2 und Grok 4.2 als externe Agents
- Wie werden Cloud-Modelle in den Discussion Loop eingebunden?

### 6. Persistent Discussion in der neuen Architektur
- 4 Agents diskutieren permanent (Grok-Style)
- Wie verteilen sich die Agents ueber die Nodes?
- Chef (120B Cloud) + Reasoner (30B Jetson) + Researcher (Cloud) + Archivist (Memory, lokal)

## Unsere Hardware

| Node | Hardware | RAM | GPU | Modelle | Latenz |
|------|----------|-----|-----|---------|--------|
| Jetson Orin | ARM, MAXN | 64 GB shared | Orin GPU | 19 + SpecDec | 1ms lokal |
| Desktop | i9, RTX 5090 | 64 GB + 32 GB VRAM | RTX 5090 | 22 | 30ms |
| Zenbook | Intel, NPU | 16 GB | Phi Silica NPU | 4 | 19ms |
| S24 Ultra | Snapdragon | 12 GB | Adreno | 1 (qwen3.5:0.8b) | ~50ms |
| Cloud | Ollama Cloud | - | - | Nemotron-120B, GPT-5.2, Grok 4.2 | 100-500ms |

## Constraints
- Alles muss in Python (FastAPI) sein
- Ollama ist der primaere Inference-Backend (+ llama.cpp fuer SpecDec)
- Memory muss IMMER erhalten bleiben (Six-Layer Memory System)
- Jede Erkenntnis aus Discussions wird gespeichert
- Kleine Modelle bevorzugen wo moeglich (Effizienz > Qualitaet fuer einfache Tasks)

## Output-Format

Gib mir:
1. **Architektur-Diagramm** (ASCII oder Mermaid)
2. **micro_orchestrator.py** — Der lokale Orchestrator (laeuft auf JEDEM Geraet)
3. **central_orchestrator.py** — Der neue zentrale Orchestrator
4. **protocol.py** — Communication Protocol zwischen den Orchestratoren
5. **config fuer jedes Geraet** — Was laeuft wo

Denke wie ein System-Architekt der ein verteiltes System fuer 5+ Nodes baut. Kein Overengineering — pragmatisch, funktional, erweiterbar.
