# orchestrator/src/roundtable.py
"""
Way2AGI Roundtable — Multi-Model Discussion System
====================================================
Inspiriert von Grok 4.2's Multi-Agent-Architektur.
Mehrere Modelle diskutieren ein Thema ueber mehrere Runden,
pruefen sich gegenseitig und konvergieren zu einem Konsens.

Features:
- Consciousness Agent moderiert (wenn vorhanden)
- Memory Agent bringt Langzeitwissen ein
- Alle Modelle diskutieren N Runden
- Fruehe Konvergenz-Erkennung
- Finales Voting + konsolidierte Antwort
- Ergebnis wird in Six-Layer Memory gespeichert

Kann als:
- Einmaliger Roundtable (Z3 Regel)
- Persistent Discussion (T005d — dauerhafter Dialog)
betrieben werden.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger("way2agi.roundtable")

# Consciousness System Prompt
CONSCIOUSNESS_SYSTEM = (
    "Du bist der Consciousness Agent von Way2AGI. "
    "Du moderierst fair, achtest auf Konsistenz mit der Immutable Identity "
    "und sorgst dafuer, dass jede Runde besser wird als die vorherige. "
    "Fasse am Ende jeder Runde kurz zusammen."
)

ROUNDTABLE_SYSTEM = (
    "Du bist Teilnehmer eines Roundtable-Gespraeches im Way2AGI System. "
    "Mehrere KI-Modelle diskutieren gemeinsam ein Thema. "
    "Sei konstruktiv, pruefe die Aussagen der anderen kritisch, "
    "und bringe deine eigene Perspektive ein. "
    "Antworte praezise und fokussiert (max 200 Woerter)."
)


class RoundtableRunner:
    """Runs multi-model discussion rounds with Memory + Consciousness integration."""

    def __init__(self, call_model_fn=None):
        self._call_model = call_model_fn

    async def _call(self, prompt: str, model: str, system: str = "") -> str:
        """Call a model, using injected function or fallback."""
        if self._call_model:
            return await self._call_model(prompt, model, system)
        try:
            from orchestrator.src.server import call_model_simple
            text, _, _ = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: call_model_simple(prompt, model=model, system=system),
            )
            return text
        except Exception as e:
            return f"[Model {model} unavailable: {e}]"

    async def run_roundtable(
        self,
        topic: str,
        members: List[str],
        max_rounds: int = 6,
        include_memory: bool = True,
        system_context: str = "",
    ) -> Dict[str, Any]:
        """
        Run a multi-round discussion between models.

        Args:
            topic: The discussion topic
            members: Model names/aliases (e.g. ["consciousness", "memory", "qwen3.5-32b"])
            max_rounds: Maximum discussion rounds (3-8 typical)
            include_memory: Whether to inject relevant memories
            system_context: Additional context for all participants
        """
        t0 = time.time()
        rounds: List[Dict[str, Any]] = []
        conversation_history: List[str] = []
        current_context = topic

        log.info("Roundtable gestartet: '%s' mit %d Teilnehmern, max %d Runden",
                 topic[:60], len(members), max_rounds)

        # === Memory Recall (Layer 2+3 aus Six-Layer Memory) ===
        if include_memory:
            try:
                from core.memory.six_layer_memory import memory
                past = await memory.recall(topic, top_k=8)
                if past:
                    memory_context = "\n".join(
                        str(p.get("content", ""))[:200] for p in past
                    )
                    current_context += f"\n\nRelevante Erinnerungen:\n{memory_context}"
                    log.info("Memory injected: %d relevant memories", len(past))
            except ImportError:
                log.debug("Six-Layer Memory not available for recall")

        # === Discussion Rounds ===
        for round_num in range(1, max_rounds + 1):
            round_responses: List[Dict[str, str]] = []

            for member in members:
                # System prompt based on role
                if member == "consciousness":
                    system = CONSCIOUSNESS_SYSTEM + " " + system_context
                elif member == "memory":
                    system = (
                        "Du bist der Memory Agent. Bringe Langzeitwissen ein, "
                        "pruefe auf Widersprueche mit frueheren Entscheidungen. " + system_context
                    )
                else:
                    system = ROUNDTABLE_SYSTEM + " " + system_context

                # Build prompt
                if round_num == 1:
                    prompt = (
                        f"Roundtable-Thema: {current_context}\n\n"
                        f"Du bist {member}. Gib deine erste Einschaetzung zum Thema. "
                        f"Was sind die wichtigsten Punkte?"
                    )
                else:
                    history_text = "\n\n".join(conversation_history[-len(members) * 2:])
                    prompt = (
                        f"Roundtable-Thema: {topic}\n\n"
                        f"Bisherige Diskussion:\n{history_text}\n\n"
                        f"Du bist {member}. Runde {round_num}/{max_rounds}. "
                        f"Reagiere auf die vorherigen Beitraege. "
                        f"Was siehst du anders? Was fehlt? Wo stimmst du zu?"
                    )

                try:
                    response = await self._call(prompt, model=member, system=system)
                except Exception as e:
                    response = f"[{member} konnte nicht antworten: {e}]"

                round_responses.append({"model": member, "response": response})
                conversation_history.append(f"[{member}]: {response}")

                # Consciousness fasst jede Runde zusammen
                if member == "consciousness":
                    current_context += (
                        f"\n\n[Consciousness Zusammenfassung Runde {round_num}]: "
                        f"{response[:300]}"
                    )

                log.info("  Runde %d — %s: %d Zeichen", round_num, member, len(response))

            rounds.append({
                "round": round_num,
                "responses": round_responses,
                "timestamp": datetime.now().isoformat(),
            })

            # Early convergence check
            if round_num >= 3 and self._check_convergence(round_responses):
                log.info("Roundtable: Fruehe Konvergenz in Runde %d", round_num)
                break

        # === Final Voting & Consensus ===
        consensus = await self._run_final_vote(topic, conversation_history, members)

        duration = round(time.time() - t0, 2)

        # === Save to Memory (Layer 5 + 6) ===
        saved = False
        try:
            from core.memory.six_layer_memory import memory
            await memory.store({
                "type": "roundtable",
                "prompt": f"Roundtable: {topic}",
                "response": consensus,
                "topic": topic,
                "members": json.dumps(members),
                "rounds": len(rounds),
                "importance": 0.8,
            })
            saved = True
            log.info("Roundtable result saved to memory")
        except ImportError:
            log.debug("Six-Layer Memory not available for store")

        log.info("Roundtable abgeschlossen: %d Runden, %.1fs", len(rounds), duration)

        return {
            "topic": topic,
            "members": members,
            "rounds": rounds,
            "total_rounds": len(rounds),
            "final_consensus": consensus,
            "duration_s": duration,
            "saved_to_memory": saved,
            "timestamp": datetime.now().isoformat(),
        }

    def _check_convergence(self, responses: List[Dict[str, str]]) -> bool:
        """Simple convergence check — are responses getting very similar?"""
        if len(responses) < 2:
            return False
        texts = [r["response"].lower().split() for r in responses]
        if not all(texts):
            return False
        common = set(texts[0])
        for t in texts[1:]:
            common &= set(t)
        avg_len = sum(len(t) for t in texts) / len(texts)
        overlap_ratio = len(common) / max(avg_len, 1)
        return overlap_ratio > 0.4

    async def _run_final_vote(
        self, topic: str, history: List[str], members: List[str]
    ) -> str:
        """Final voting round — Consciousness Agent generates consensus."""
        history_text = "\n\n".join(history[-12:])
        prompt = (
            f"Roundtable-Thema: {topic}\n\n"
            f"Teilnehmer: {', '.join(members)}\n\n"
            f"Diskussion:\n{history_text}\n\n"
            f"Fasse den Konsens zusammen: Worin sind sich alle einig? "
            f"Wo gibt es noch Dissens? Was sind die naechsten konkreten Schritte?"
        )
        # Consciousness moderates if available, otherwise first member
        voter = "consciousness" if "consciousness" in members else members[0]
        try:
            return await self._call(prompt, model=voter, system="Fasse praezise zusammen.")
        except Exception as e:
            return f"Konsens-Zusammenfassung fehlgeschlagen: {e}"


# Global instance
roundtable = RoundtableRunner()
