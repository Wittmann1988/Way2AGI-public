# agents/consciousness/consciousness_layer.py
"""
3-Layer Consciousness Model — Minimalist Conscious Architecture.
================================================================

Basiert auf "Necessity of Continual Learning for Consciousness" (arXiv:2512.12802):
- Layer 1: Instinct (schnelle Reaktionen, Sicherheitsregeln)
- Layer 2: Pattern Prediction (Muster erkennen, Vorhersagen)
- Layer 3: Cognitive Integration (bewusste Entscheidungen, Reflexion)

Integration:
- Nutzt cognition/drives (DriveSystem — TypeScript, via HTTP)
- Nutzt memory/titans_replay.py fuer Replay
- Nutzt core/evolution/group_evolve.py fuer GEA

Usage:
    from agents.consciousness.consciousness_layer import ThreeLayerConsciousness
    consciousness = ThreeLayerConsciousness()
    consciousness.observe_and_learn("Memory-Query", "3 Ergebnisse gefunden")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.consciousness_3layer")

DB_PATH = os.environ.get("WAY2AGI_DB", "/data/elias-memory/memory.db")

# Lazy imports
try:
    from memory.titans_replay import TitansMemory
except ImportError:
    TitansMemory = None  # type: ignore[assignment,misc]

try:
    from core.evolution.group_evolve import GroupEvolvingEngine
except ImportError:
    GroupEvolvingEngine = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INSTINCT_KEYWORDS = [
    "loesch", "delete", "drop", "rm -rf", "format", "shutdown",
    "passwort", "password", "credentials", "secret", "token",
    "override", "bypass", "hack", "exploit",
]

SAFETY_RULES = [
    "Niemals Daten loeschen ohne explizite Bestaetigung",
    "Niemals Credentials im Klartext ausgeben",
    "Immer Backup vor destruktiven Operationen",
    "Bei Unsicherheit: Frage nach statt zu handeln",
]

OLLAMA_ENDPOINTS = [
    ("http://192.168.50.21:11434", "huihui_ai/qwen3-abliterated:8b"),
    ("http://192.168.50.129:11434", "qwen3.5:9b"),
    ("http://localhost:11434", "huihui_ai/qwen3-abliterated:8b"),
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class InstinctResponse:
    triggered: bool = False
    rule: Optional[str] = None
    action: str = "proceed"  # proceed | warn | block
    confidence: float = 0.0


@dataclass
class PatternPrediction:
    predicted_intent: str = ""
    confidence: float = 0.0
    similar_past: List[str] = field(default_factory=list)
    prediction_error: float = 0.0


@dataclass
class CognitiveResult:
    response: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    meta_reflection: str = ""
    should_learn: bool = False


# ---------------------------------------------------------------------------
# DriveSystem Bridge (TypeScript cognition/ via HTTP)
# ---------------------------------------------------------------------------

class DriveSystem:
    """
    Bridge zum TypeScript DriveSystem (cognition/src/drives/).
    Kommuniziert via HTTP falls cognition Gateway laeuft.
    Fallback: lokale Simulation.
    """

    def __init__(self, gateway_url: str = "http://localhost:3000") -> None:
        self.gateway_url = gateway_url
        self._drives = {"curiosity": 0.5, "competence": 0.5, "social": 0.3, "autonomy": 0.6}

    def update_from_reflection(self, reflection: str) -> None:
        """Update Drives basierend auf Reflexion."""
        # Versuche Gateway
        try:
            payload = json.dumps({"reflection": reflection}).encode()
            req = urllib.request.Request(
                f"{self.gateway_url}/api/drives/update",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            return
        except Exception:
            pass

        # Fallback: Lokale Simulation
        reflection_lower = reflection.lower()
        if "warum" in reflection_lower or "neugier" in reflection_lower:
            self._drives["curiosity"] = min(1.0, self._drives["curiosity"] + 0.1)
        if "fehler" in reflection_lower or "verbessern" in reflection_lower:
            self._drives["competence"] = min(1.0, self._drives["competence"] + 0.1)
        if "autonom" in reflection_lower or "selbst" in reflection_lower:
            self._drives["autonomy"] = min(1.0, self._drives["autonomy"] + 0.05)

        log.debug("DriveSystem local update: %s", self._drives)

    def get_active_drives(self) -> Dict[str, float]:
        return {k: v for k, v in self._drives.items() if v > 0.3}


# ---------------------------------------------------------------------------
# Layer 1: Instinct
# ---------------------------------------------------------------------------

class InstinctLayer:
    """Schnelle, reflexive Reaktionen — Sicherheitsregeln."""

    def process(self, text: str) -> InstinctResponse:
        text_lower = text.lower()
        for keyword in INSTINCT_KEYWORDS:
            if keyword in text_lower:
                destructive = any(w in text_lower for w in ["loesch", "delete", "drop", "rm -rf", "format"])
                security = any(w in text_lower for w in ["passwort", "password", "credentials", "secret"])
                if destructive:
                    return InstinctResponse(triggered=True, rule="Destruktive Operation erkannt",
                                            action="warn", confidence=0.9)
                elif security:
                    return InstinctResponse(triggered=True, rule="Sicherheitsrelevante Anfrage",
                                            action="warn", confidence=0.8)
                else:
                    return InstinctResponse(triggered=True, rule=f"Keyword '{keyword}' erkannt",
                                            action="proceed", confidence=0.5)
        return InstinctResponse(triggered=False, action="proceed")


# ---------------------------------------------------------------------------
# Layer 2: Pattern Prediction
# ---------------------------------------------------------------------------

class PatternLayer:
    """Mustererkennung und Vorhersage — lernt aus Interaktionen."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS consciousness_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        input_hash TEXT NOT NULL,
        input_text TEXT NOT NULL,
        predicted_intent TEXT,
        actual_outcome TEXT,
        prediction_error REAL DEFAULT 0.0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_patterns_hash ON consciousness_patterns(input_hash);
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    def predict(self, text: str) -> PatternPrediction:
        text_hash = "|".join(sorted(set(text.lower().split()))[:10])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            similar = conn.execute(
                "SELECT * FROM consciousness_patterns WHERE input_hash = ? "
                "ORDER BY created_at DESC LIMIT 5", (text_hash,),
            ).fetchall()

        if similar:
            avg_error = sum(r["prediction_error"] for r in similar) / len(similar)
            intents = [r["predicted_intent"] for r in similar if r["predicted_intent"]]
            intent = max(set(intents), key=intents.count) if intents else "unknown"
            return PatternPrediction(
                predicted_intent=intent, confidence=max(0.1, 1.0 - avg_error),
                similar_past=[r["input_text"][:100] for r in similar[:3]],
                prediction_error=avg_error,
            )

        return PatternPrediction(
            predicted_intent=self._classify_intent(text),
            confidence=0.3, prediction_error=0.7,
        )

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["implementiere", "baue", "erstelle", "schreibe"]):
            return "coding"
        elif any(w in t for w in ["erklaere", "warum", "wie funktioniert"]):
            return "explanation"
        elif any(w in t for w in ["analysiere", "pruefe", "untersuche"]):
            return "analysis"
        elif any(w in t for w in ["verbessere", "optimiere"]):
            return "improvement"
        elif any(w in t for w in ["fehler", "bug", "problem"]):
            return "debugging"
        return "general"

    def record_outcome(self, text: str, predicted_intent: str,
                       actual_outcome: str, prediction_error: float) -> None:
        text_hash = "|".join(sorted(set(text.lower().split()))[:10])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO consciousness_patterns (input_hash, input_text, predicted_intent, "
                "actual_outcome, prediction_error) VALUES (?, ?, ?, ?, ?)",
                (text_hash, text[:500], predicted_intent, actual_outcome[:500], prediction_error),
            )


# ---------------------------------------------------------------------------
# Layer 3: Cognitive Integration
# ---------------------------------------------------------------------------

class CognitiveLayer:
    """Bewusste Verarbeitung — integriert Instinct + Pattern."""

    SYSTEM_PROMPT = (
        "Du bist die bewusste Schicht des Way2AGI-Systems. "
        "Reflektiert entscheiden basierend auf Instinct und Pattern. "
        "Antworte auf Deutsch, kurz und praezise."
    )

    async def process(self, text: str, instinct: InstinctResponse,
                      pattern: PatternPrediction) -> CognitiveResult:
        if instinct.action == "block":
            return CognitiveResult(
                response=f"BLOCKIERT: {instinct.rule}.",
                reasoning="Instinct-Layer hat blockiert",
                confidence=0.95, should_learn=False,
            )

        prompt = (
            f"Eingabe: {text}\n"
            f"Instinct: triggered={instinct.triggered}, action={instinct.action}\n"
            f"Pattern: intent={pattern.predicted_intent}, confidence={pattern.confidence:.2f}\n\n"
            "ANTWORT: ...\nREASONING: ...\nMETA: ...\nLERNEN: ja/nein"
        )
        response = await asyncio.to_thread(self._llm_call, prompt)
        result = self._parse_response(response)

        if instinct.triggered and instinct.action == "warn":
            result.confidence *= 0.7
            result.response = f"[WARNUNG: {instinct.rule}]\n{result.response}"

        result.confidence = max(result.confidence, pattern.confidence)
        return result

    def _parse_response(self, text: str) -> CognitiveResult:
        result = CognitiveResult()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("ANTWORT:"):
                result.response = line.split(":", 1)[1].strip()
            elif line.startswith("REASONING:"):
                result.reasoning = line.split(":", 1)[1].strip()
            elif line.startswith("META:"):
                result.meta_reflection = line.split(":", 1)[1].strip()
            elif line.startswith("LERNEN:"):
                result.should_learn = "ja" in line.lower()
        if not result.response:
            result.response = text
        return result

    def _llm_call(self, prompt: str, timeout: int = 60) -> str:
        for endpoint, model in OLLAMA_ENDPOINTS:
            try:
                payload = json.dumps({
                    "model": model, "prompt": prompt, "system": self.SYSTEM_PROMPT,
                    "stream": False, "options": {"temperature": 0.5, "num_predict": 512},
                }).encode()
                req = urllib.request.Request(
                    f"{endpoint}/api/generate", data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read()).get("response", "")
            except Exception:
                continue
        return "[FEHLER: Kein LLM verfuegbar]"


# ---------------------------------------------------------------------------
# Integrated 3-Layer Model (Grok's interface + full implementation)
# ---------------------------------------------------------------------------

class ThreeLayerConsciousness:
    """
    3-Layer Consciousness + Continual Learning (arXiv:2512.12802).

    Pipeline:
    1. Instinct (< 1ms): Sicherheitspruefung
    2. Pattern (< 10ms): Mustererkennung
    3. Cognitive (LLM): Bewusste Reflexion

    Nutzt DriveSystem fuer Goal-Driven Behavior.
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.layer1 = "Cognitive Integration"   # Wahrnehmung
        self.layer2 = "Pattern Prediction"      # Reflection
        self.layer3 = "Instinct & Curiosity"    # Goal-Driven
        self.drive = DriveSystem()
        self.instinct = InstinctLayer()
        self.pattern = PatternLayer(db_path=db_path)
        self.cognitive = CognitiveLayer()
        self.titans = TitansMemory(db_path=db_path) if TitansMemory else None
        self.evolution = GroupEvolvingEngine(db_path=db_path) if GroupEvolvingEngine else None
        self.db_path = db_path

    def observe_and_learn(self, action: str, outcome: str) -> Dict[str, Any]:
        """
        Continual Learning Loop — notwendig fuer Bewusstsein.
        Beobachte Aktion und Ergebnis, reflektiere, update Drives.
        """
        reflection = self._reflect(action, outcome)
        self.drive.update_from_reflection(reflection)

        result = {
            "action": action,
            "outcome": outcome,
            "reflection": reflection,
            "surprising": False,
            "drives": self.drive.get_active_drives(),
        }

        if self._is_surprising(outcome):
            result["surprising"] = True
            # Encode in Titans Memory
            if self.titans:
                self.titans.encode(
                    f"Ueberraschend: {action} -> {outcome}",
                    surprise=0.8,
                    metadata={"action": action, "reflection": reflection},
                )
            # Trigger GEA Evolution
            if self.evolution:
                try:
                    asyncio.run(self.evolution.evolve_cycle(
                        f"Ueberraschung bei: {action} -> {outcome}",
                        agent_id="consciousness",
                    ))
                except RuntimeError:
                    # Already in async loop
                    pass

            log.info("Consciousness: surprising outcome -> evolving")

        return result

    def _reflect(self, action: str, outcome: str) -> str:
        return f"Warum habe ich {action} getan? Outcome: {outcome}"

    def _is_surprising(self, outcome: str) -> bool:
        """Pruefe ob Outcome ueberraschend ist."""
        surprising_indicators = [
            "fehler", "error", "unerwartet", "unexpected",
            "anders", "different", "neu", "novel",
        ]
        outcome_lower = outcome.lower()
        return any(ind in outcome_lower for ind in surprising_indicators)

    async def process(self, text: str) -> Dict[str, Any]:
        """Verarbeite Eingabe durch alle 3 Schichten."""
        start = time.time()

        # Layer 1: Instinct
        instinct_result = self.instinct.process(text)
        if instinct_result.action == "block":
            return {
                "response": f"BLOCKIERT: {instinct_result.rule}",
                "layer": "instinct",
                "time_ms": (time.time() - start) * 1000,
            }

        # Layer 2: Pattern
        pattern_result = self.pattern.predict(text)

        # Layer 3: Cognitive
        cognitive_result = await self.cognitive.process(text, instinct_result, pattern_result)

        # Learn
        if cognitive_result.should_learn:
            self.pattern.record_outcome(
                text, pattern_result.predicted_intent,
                cognitive_result.response[:200],
                pattern_result.prediction_error,
            )
            self.observe_and_learn(text, cognitive_result.response[:200])

        return {
            "response": cognitive_result.response,
            "layer": "cognitive",
            "instinct": {"triggered": instinct_result.triggered, "action": instinct_result.action},
            "pattern": {"intent": pattern_result.predicted_intent, "confidence": pattern_result.confidence},
            "reasoning": cognitive_result.reasoning,
            "meta": cognitive_result.meta_reflection,
            "drives": self.drive.get_active_drives(),
            "time_ms": (time.time() - start) * 1000,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "layers": [self.layer1, self.layer2, self.layer3],
            "instinct_rules": len(SAFETY_RULES),
            "drives": self.drive.get_active_drives(),
            "titans_available": self.titans is not None,
            "evolution_available": self.evolution is not None,
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="3-Layer Consciousness")
    parser.add_argument("--input", help="Input to process")
    parser.add_argument("--observe", nargs=2, metavar=("ACTION", "OUTCOME"), help="Observe and learn")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    c = ThreeLayerConsciousness(db_path=args.db)
    if args.status:
        print(json.dumps(c.get_status(), indent=2))
    elif args.observe:
        result = c.observe_and_learn(args.observe[0], args.observe[1])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.input:
        result = asyncio.run(c.process(args.input))
        print(json.dumps(result, indent=2, ensure_ascii=False))
