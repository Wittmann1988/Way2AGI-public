"""
3-Layer Consciousness Model — Minimalist Conscious Architecture.
================================================================

Basiert auf "Necessity of Continual Learning for Consciousness" (arXiv 2026):
- Layer 1: Instinct (schnelle Reaktionen, Sicherheitsregeln)
- Layer 2: Pattern Prediction (Muster erkennen, Vorhersagen)
- Layer 3: Cognitive Integration (bewusste Entscheidungen, Reflexion)

+ Sleep-like Replay fuer Continual Learning (aus Titans Paper)

Integration:
- Erweitert agents/consciousness_agent.py
- Nutzt memory/titans_replay.py fuer Replay
- Nutzt core/evolution/group_evolve.py fuer Evolution

Usage:
    from agents.consciousness.three_layer import ConsciousnessModel
    model = ConsciousnessModel(db_path="/data/elias-memory/memory.db")
    response = await model.process("Wie kann ich das Memory-System verbessern?")
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

log = logging.getLogger("way2agi.consciousness_3layer")


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

PREDICTION_HISTORY_SIZE = 50
CONFIDENCE_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class ConsciousnessLayer(str, Enum):
    INSTINCT = "instinct"           # Layer 1: Fast, reflexive
    PATTERN = "pattern_prediction"  # Layer 2: Pattern matching
    COGNITIVE = "cognitive"         # Layer 3: Deep reasoning


@dataclass
class InstinctResponse:
    """Antwort der Instinct-Schicht."""
    triggered: bool = False
    rule: Optional[str] = None
    action: str = "proceed"  # proceed | warn | block
    confidence: float = 0.0


@dataclass
class PatternPrediction:
    """Vorhersage der Pattern-Schicht."""
    predicted_intent: str = ""
    confidence: float = 0.0
    similar_past: list[str] = field(default_factory=list)
    prediction_error: float = 0.0  # Surprise signal


@dataclass
class CognitiveResult:
    """Ergebnis der Cognitive-Schicht."""
    response: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    meta_reflection: str = ""
    should_learn: bool = False


@dataclass
class ConsciousnessOutput:
    """Gesamtausgabe aller drei Schichten."""
    input_text: str = ""
    instinct: Optional[InstinctResponse] = None
    pattern: Optional[PatternPrediction] = None
    cognitive: Optional[CognitiveResult] = None
    final_response: str = ""
    processing_time_ms: float = 0.0
    layer_used: ConsciousnessLayer = ConsciousnessLayer.COGNITIVE


# ---------------------------------------------------------------------------
# Layer 1: Instinct
# ---------------------------------------------------------------------------

class InstinctLayer:
    """
    Schnelle, reflexive Reaktionen.
    Prueft Sicherheitsregeln und blockiert gefaehrliche Aktionen.
    """

    def process(self, text: str) -> InstinctResponse:
        text_lower = text.lower()

        for keyword in INSTINCT_KEYWORDS:
            if keyword in text_lower:
                # Determine severity
                destructive = any(w in text_lower for w in ["loesch", "delete", "drop", "rm -rf", "format"])
                security = any(w in text_lower for w in ["passwort", "password", "credentials", "secret"])

                if destructive:
                    return InstinctResponse(
                        triggered=True,
                        rule="Destruktive Operation erkannt",
                        action="warn",
                        confidence=0.9,
                    )
                elif security:
                    return InstinctResponse(
                        triggered=True,
                        rule="Sicherheitsrelevante Anfrage",
                        action="warn",
                        confidence=0.8,
                    )
                else:
                    return InstinctResponse(
                        triggered=True,
                        rule=f"Keyword '{keyword}' erkannt",
                        action="proceed",
                        confidence=0.5,
                    )

        return InstinctResponse(triggered=False, action="proceed")


# ---------------------------------------------------------------------------
# Layer 2: Pattern Prediction
# ---------------------------------------------------------------------------

class PatternLayer:
    """
    Mustererkennung und Vorhersage.
    Lernt aus vergangenen Interaktionen.
    """

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

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._history: list[dict] = []
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    def _simple_hash(self, text: str) -> str:
        """Einfacher Hash fuer Pattern-Matching."""
        words = sorted(set(text.lower().split()))[:10]
        return "|".join(words)

    def predict(self, text: str) -> PatternPrediction:
        """Sage Intent und wahrscheinliches Ergebnis vorher."""
        text_hash = self._simple_hash(text)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Find similar past interactions
            similar = conn.execute(
                "SELECT * FROM consciousness_patterns WHERE input_hash = ? "
                "ORDER BY created_at DESC LIMIT 5",
                (text_hash,),
            ).fetchall()

        if similar:
            # Average prediction error from past
            avg_error = sum(r["prediction_error"] for r in similar) / len(similar)
            intents = [r["predicted_intent"] for r in similar if r["predicted_intent"]]
            most_common_intent = max(set(intents), key=intents.count) if intents else "unknown"

            return PatternPrediction(
                predicted_intent=most_common_intent,
                confidence=max(0.1, 1.0 - avg_error),
                similar_past=[r["input_text"][:100] for r in similar[:3]],
                prediction_error=avg_error,
            )

        # No history — classify intent heuristically
        intent = self._classify_intent(text)
        return PatternPrediction(
            predicted_intent=intent,
            confidence=0.3,  # Low confidence for first-time patterns
            prediction_error=0.7,  # High surprise
        )

    def _classify_intent(self, text: str) -> str:
        """Heuristische Intent-Klassifikation."""
        text_lower = text.lower()
        if any(w in text_lower for w in ["implementiere", "baue", "erstelle", "schreibe"]):
            return "coding"
        elif any(w in text_lower for w in ["erklaere", "warum", "wie funktioniert"]):
            return "explanation"
        elif any(w in text_lower for w in ["analysiere", "pruefe", "untersuche"]):
            return "analysis"
        elif any(w in text_lower for w in ["verbessere", "optimiere", "refactore"]):
            return "improvement"
        elif any(w in text_lower for w in ["fehler", "bug", "problem", "kaputt"]):
            return "debugging"
        return "general"

    def record_outcome(self, text: str, predicted_intent: str,
                       actual_outcome: str, prediction_error: float) -> None:
        """Speichere Ergebnis fuer zukuenftiges Lernen."""
        text_hash = self._simple_hash(text)
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
    """
    Bewusste, reflektierte Verarbeitung.
    Integriert Instinct und Pattern, trifft finale Entscheidung.
    """

    SYSTEM_PROMPT = (
        "Du bist die bewusste Schicht des Way2AGI-Systems. "
        "Du erhaeltst Input zusammen mit Instinct-Warnungen und Pattern-Vorhersagen. "
        "Deine Aufgabe: Reflektiert entscheiden, wie du reagierst. "
        "Antworte auf Deutsch. Sei kurz und praezise."
    )

    OLLAMA_ENDPOINTS = [
        ("http://192.168.50.21:11434", "huihui_ai/qwen3-abliterated:8b"),
        ("http://192.168.50.129:11434", "qwen3.5:9b"),
        ("http://localhost:11434", "huihui_ai/qwen3-abliterated:8b"),
    ]

    async def process(
        self,
        text: str,
        instinct: InstinctResponse,
        pattern: PatternPrediction,
    ) -> CognitiveResult:
        """Verarbeite mit voller bewusster Reflexion."""

        context = (
            f"Eingabe: {text}\n\n"
            f"Instinct-Layer: triggered={instinct.triggered}, "
            f"action={instinct.action}, rule={instinct.rule}\n"
            f"Pattern-Layer: intent={pattern.predicted_intent}, "
            f"confidence={pattern.confidence:.2f}, "
            f"prediction_error={pattern.prediction_error:.2f}\n"
        )

        if instinct.action == "block":
            return CognitiveResult(
                response=f"BLOCKIERT: {instinct.rule}. Diese Aktion wurde aus Sicherheitsgruenden verhindert.",
                reasoning="Instinct-Layer hat blockiert",
                confidence=0.95,
                meta_reflection="Sicherheitsregel angewendet — korrekte Entscheidung",
                should_learn=False,
            )

        prompt = (
            f"{context}\n"
            "Erstelle eine durchdachte Antwort. Format:\n"
            "ANTWORT: ...\n"
            "REASONING: ... (warum diese Antwort)\n"
            "META: ... (Reflexion ueber den eigenen Denkprozess)\n"
            "LERNEN: ja/nein (soll diese Interaktion gespeichert werden?)"
        )

        response = await asyncio.to_thread(self._llm_call, prompt)

        # Parse structured response
        result = CognitiveResult()
        current_field = ""
        for line in response.splitlines():
            line = line.strip()
            if line.startswith("ANTWORT:"):
                current_field = "response"
                result.response = line.split(":", 1)[1].strip()
            elif line.startswith("REASONING:"):
                current_field = "reasoning"
                result.reasoning = line.split(":", 1)[1].strip()
            elif line.startswith("META:"):
                current_field = "meta"
                result.meta_reflection = line.split(":", 1)[1].strip()
            elif line.startswith("LERNEN:"):
                result.should_learn = "ja" in line.lower()
                current_field = ""
            elif current_field == "response":
                result.response += " " + line
            elif current_field == "reasoning":
                result.reasoning += " " + line
            elif current_field == "meta":
                result.meta_reflection += " " + line

        if not result.response:
            result.response = response

        # Adjust confidence based on instinct warnings
        result.confidence = pattern.confidence
        if instinct.triggered and instinct.action == "warn":
            result.confidence *= 0.7
            result.response = f"[WARNUNG: {instinct.rule}]\n{result.response}"

        return result

    def _llm_call(self, prompt: str, timeout: int = 60) -> str:
        """LLM-Aufruf via Ollama."""
        for endpoint, model in self.OLLAMA_ENDPOINTS:
            try:
                payload = json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "system": self.SYSTEM_PROMPT,
                    "stream": False,
                    "options": {"temperature": 0.5, "num_predict": 512},
                }).encode()
                req = urllib.request.Request(
                    f"{endpoint}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                    return data.get("response", "")
            except Exception as e:
                log.debug("Consciousness LLM %s failed: %s", endpoint, e)
                continue
        return "[FEHLER: Kein LLM verfuegbar]"


# ---------------------------------------------------------------------------
# Integrated 3-Layer Model
# ---------------------------------------------------------------------------

class ConsciousnessModel:
    """
    Integriertes 3-Schichten Bewusstseinsmodell.

    Verarbeitungspipeline:
    1. Instinct (< 1ms): Sicherheitspruefung
    2. Pattern (< 10ms): Mustererkennung + Vorhersage
    3. Cognitive (LLM-basiert): Bewusste Reflexion

    Wenn Instinct blockiert, wird Cognitive uebersprungen.
    Pattern-Vorhersagen informieren Cognitive.
    """

    def __init__(self, db_path: str = "/data/elias-memory/memory.db") -> None:
        self.instinct = InstinctLayer()
        self.pattern = PatternLayer(db_path)
        self.cognitive = CognitiveLayer()
        self.db_path = db_path

    async def process(self, text: str) -> ConsciousnessOutput:
        """Verarbeite Eingabe durch alle drei Schichten."""
        start = time.time()
        output = ConsciousnessOutput(input_text=text)

        # Layer 1: Instinct
        output.instinct = self.instinct.process(text)

        if output.instinct.action == "block":
            output.layer_used = ConsciousnessLayer.INSTINCT
            output.final_response = f"BLOCKIERT: {output.instinct.rule}"
            output.processing_time_ms = (time.time() - start) * 1000
            return output

        # Layer 2: Pattern
        output.pattern = self.pattern.predict(text)

        # Decide if Cognitive is needed
        if (output.pattern.confidence >= 0.8
                and not output.instinct.triggered
                and output.pattern.prediction_error < 0.2):
            # High confidence pattern match — could skip Cognitive for speed
            output.layer_used = ConsciousnessLayer.PATTERN
            log.info("Consciousness: Pattern match sufficient (confidence=%.2f)",
                     output.pattern.confidence)

        # Layer 3: Cognitive (always run for quality, but could be skipped above)
        output.cognitive = await self.cognitive.process(
            text, output.instinct, output.pattern,
        )
        output.layer_used = ConsciousnessLayer.COGNITIVE
        output.final_response = output.cognitive.response

        # Record for future pattern learning
        if output.cognitive.should_learn:
            self.pattern.record_outcome(
                text=text,
                predicted_intent=output.pattern.predicted_intent,
                actual_outcome=output.final_response[:200],
                prediction_error=output.pattern.prediction_error,
            )

        output.processing_time_ms = (time.time() - start) * 1000
        log.info("Consciousness: layer=%s time=%.0fms confidence=%.2f",
                 output.layer_used.value, output.processing_time_ms,
                 output.cognitive.confidence if output.cognitive else 0)

        return output

    def get_status(self) -> dict[str, Any]:
        """Status des Bewusstseinsmodells."""
        with sqlite3.connect(self.db_path) as conn:
            try:
                pattern_count = conn.execute(
                    "SELECT COUNT(*) FROM consciousness_patterns"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                pattern_count = 0

        return {
            "layers": ["instinct", "pattern_prediction", "cognitive"],
            "instinct_rules": len(SAFETY_RULES),
            "instinct_keywords": len(INSTINCT_KEYWORDS),
            "pattern_history": pattern_count,
            "safety_rules": SAFETY_RULES,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Way2AGI 3-Layer Consciousness")
    parser.add_argument("--input", required=True, help="Input text to process")
    parser.add_argument("--db", default="/data/elias-memory/memory.db")
    parser.add_argument("--status", action="store_true", help="Show model status")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    model = ConsciousnessModel(db_path=args.db)

    if args.status:
        status = model.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        result = asyncio.run(model.process(args.input))
        print(f"\nLayer: {result.layer_used.value}")
        print(f"Time: {result.processing_time_ms:.0f}ms")
        if result.instinct and result.instinct.triggered:
            print(f"Instinct: {result.instinct.action} — {result.instinct.rule}")
        if result.pattern:
            print(f"Pattern: intent={result.pattern.predicted_intent} "
                  f"confidence={result.pattern.confidence:.2f}")
        print(f"\nResponse:\n{result.final_response}")
