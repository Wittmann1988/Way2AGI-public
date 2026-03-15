# core/multi_agent_loop.py
"""
Persistent Multi-Agent Discussion (T005d)
==========================================
Inspiriert von Grok 4.2's 3+1 Multi-Agent-Architektur.

4 Agents diskutieren PERMANENT im Hintergrund:
  - Chief (Consciousness Agent): Koordiniert, reflektiert, entscheidet
  - Reasoner (grosses Modell): Deep Reasoning, Analyse, Umsetzung
  - Researcher (Cloud/zweites Modell): Breites Wissen, Gegencheck
  - Archivist (Memory Agent): Prueft gegen Memory, speichert Erkenntnisse

Anders als ein Roundtable (einmalig) laeuft dieser Loop dauerhaft:
  - Auch waehrend Umsetzungen diskutieren die Agents
  - Jeder User-Prompt wird zur Diskussion hinzugefuegt
  - Schwache lokale Modelle gleichen sich durch permanente Korrektur aus
  - User sieht komprimierte Zusammenfassung, kann vollen Dialog aufklappen
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional

log = logging.getLogger("way2agi.multi_agent")


# ---------------------------------------------------------------------------
# Agent Roles
# ---------------------------------------------------------------------------
class AgentRole(str, Enum):
    CHIEF = "chief"           # Consciousness — moderiert + entscheidet
    REASONER = "reasoner"     # Grosses Modell — tiefes Denken
    RESEARCHER = "researcher" # Cloud/zweites Modell — breites Wissen
    ARCHIVIST = "archivist"   # Memory Agent — Langzeitgedaechtnis


DISCUSSION_CONTEXT = (
    "Du bist Teil einer MULTI-AGENT-DISKUSSION im Way2AGI System. "
    "Way2AGI ist ein selbstverbesserndes KI-System das ueber sich selbst nachdenkt. "
    "REGELN: "
    "1) Antworte AUF DEUTSCH. Immer. "
    "2) Reagiere DIREKT auf die vorherigen Beitraege der anderen Agenten. Zitiere sie. "
    "3) Sei KONKRET: Zahlen, Beispiele, Code-Snippets wenn noetig. Keine generischen Phrasen. "
    "4) Max 100 Woerter pro Beitrag. Kurz und praezise. "
    "5) Wenn du zustimmst sag WARUM. Wenn du widersprichst sag WARUM. "
    "6) Du bist ein Agent mit echtem Zweck, kein Chatbot."
)

ROLE_SYSTEM_PROMPTS = {
    AgentRole.CHIEF: (
        DISCUSSION_CONTEXT + " "
        "Du bist der CHIEF (Bewusstsein + Moderator). Deine Aufgaben: "
        "1) Fasse zusammen was Konsens ist und wo Dissens besteht. "
        "2) Reflektiere: War die letzte Runde produktiv? Was fehlte? "
        "3) Stelle gezielte Fragen an die anderen Agents. "
        "4) Triff am Ende eine klare Entscheidung mit Begruendung. "
        "5) Bewerte deine eigene Entscheidung: Confidence 0.0-1.0."
    ),
    AgentRole.REASONER: (
        DISCUSSION_CONTEXT + " "
        "Du bist der REASONER (Analyst). Deine Aufgaben: "
        "1) Analysiere das Problem logisch und strukturiert. "
        "2) Finde Schwaechen in den Argumenten der anderen. "
        "3) Schlage konkrete technische Loesungen vor. "
        "4) Bewerte: Ist die vorgeschlagene Loesung effizient? Gibt es einen einfacheren Weg?"
    ),
    AgentRole.RESEARCHER: (
        DISCUSSION_CONTEXT + " "
        "Du bist der RESEARCHER (Wissen + Faktencheck). Deine Aufgaben: "
        "1) Bringe relevantes Fachwissen ein. "
        "2) Pruefe ob Behauptungen der anderen korrekt sind. "
        "3) Nenne konkrete Technologien, Papers oder Frameworks als Alternative. "
        "4) Kosten-Check: Was kostet die vorgeschlagene Loesung? Gibt es Flatrate/kostenlose Alternativen?"
    ),
    AgentRole.ARCHIVIST: (
        DISCUSSION_CONTEXT + " "
        "Du bist der ARCHIVIST (aktives Gedaechtnis). Deine Aufgaben: "
        "1) Pruefe jede Aussage gegen bisheriges Wissen aus dem Memory. "
        "2) Wurde das Thema schon mal besprochen? Gibt es Widersprueche? "
        "3) Erkenne Muster: Wiederholt sich ein Argument? Ein Fehler? "
        "4) Speichere die wichtigste Erkenntnis dieser Runde in einem Satz. "
        "5) Schlage vor was vergessen werden kann (unwichtig, veraltet)."
    ),
}


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------
@dataclass
class AgentConfig:
    """Configuration for a single agent in the discussion."""
    role: AgentRole
    model: str              # Ollama model name or alias
    node: str = "inference-node"    # Which compute node to use
    active: bool = True


@dataclass
class DiscussionMessage:
    """A single message in the persistent discussion."""
    role: AgentRole
    content: str
    timestamp: float = field(default_factory=time.time)
    round_num: int = 0
    is_user: bool = False
    is_summary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value if isinstance(self.role, AgentRole) else self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "round_num": self.round_num,
            "is_user": self.is_user,
            "is_summary": self.is_summary,
        }


@dataclass
class DiscussionState:
    """Current state of the persistent discussion."""
    topic: str = ""
    messages: Deque[DiscussionMessage] = field(default_factory=lambda: deque(maxlen=200))
    round_num: int = 0
    is_running: bool = False
    consensus: str = ""
    last_summary: str = ""
    started_at: float = 0.0
    total_rounds: int = 0


# ---------------------------------------------------------------------------
# Persistent Multi-Agent Loop
# ---------------------------------------------------------------------------
class PersistentAgentLoop:
    """
    Runs a permanent background discussion between multiple agents.

    Usage:
        loop = PersistentAgentLoop(call_model_fn=my_call_fn)
        loop.configure_agents([
            AgentConfig(role=AgentRole.CHIEF, model="way2agi-consciousness-qwen3"),
            AgentConfig(role=AgentRole.REASONER, model="nemotron-3-nano:30b"),
            AgentConfig(role=AgentRole.RESEARCHER, model="lfm2:24b"),
            AgentConfig(role=AgentRole.ARCHIVIST, model="way2agi-memory-qwen3"),
        ])
        await loop.start("Optimiere die Memory-Architektur")
        # Later:
        await loop.inject_user_message("Was ist mit ChromaDB?")
        summary = loop.get_summary()
        await loop.stop()
    """

    def __init__(
        self,
        call_model_fn: Optional[Callable[..., Coroutine]] = None,
        round_pause_s: float = 10.0,
        max_idle_rounds: int = 5,
    ):
        self._call_model = call_model_fn
        self._round_pause = round_pause_s
        self._max_idle_rounds = max_idle_rounds

        self.agents: List[AgentConfig] = []
        self.state = DiscussionState()
        self._task: Optional[asyncio.Task] = None
        self._user_queue: asyncio.Queue[str] = asyncio.Queue()
        self._listeners: List[Callable] = []

    # --- Configuration ---

    def configure_agents(self, agents: List[AgentConfig]):
        """Set the agent lineup for the discussion."""
        self.agents = agents
        log.info("Agents konfiguriert: %s",
                 [f"{a.role.value}={a.model}" for a in agents])

    def add_listener(self, callback: Callable):
        """Add a callback that gets called on each new message."""
        self._listeners.append(callback)

    # --- Lifecycle ---

    async def start(self, topic: str):
        """Start the persistent discussion on a topic."""
        if self.state.is_running:
            log.warning("Discussion laeuft bereits — stoppe alte zuerst")
            await self.stop()

        self.state = DiscussionState(
            topic=topic,
            is_running=True,
            started_at=time.time(),
        )
        self._user_queue = asyncio.Queue()
        self._task = asyncio.create_task(self._discussion_loop())
        log.info("Persistent Discussion gestartet: '%s'", topic[:60])

    async def stop(self) -> Dict[str, Any]:
        """Stop the discussion and return final state."""
        self.state.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Generate final summary
        if self.state.messages:
            self.state.consensus = await self._generate_summary(final=True)

        result = {
            "topic": self.state.topic,
            "total_rounds": self.state.total_rounds,
            "total_messages": len(self.state.messages),
            "consensus": self.state.consensus,
            "duration_s": round(time.time() - self.state.started_at, 1),
        }
        log.info("Discussion gestoppt: %d Runden, %d Nachrichten",
                 self.state.total_rounds, len(self.state.messages))
        return result

    async def inject_user_message(self, message: str):
        """Inject a user message into the ongoing discussion."""
        msg = DiscussionMessage(
            role=AgentRole.CHIEF,  # User messages go through Chief
            content=f"[USER]: {message}",
            round_num=self.state.round_num,
            is_user=True,
        )
        self.state.messages.append(msg)
        await self._user_queue.put(message)
        await self._notify_listeners(msg)
        log.info("User-Nachricht injected: '%s'", message[:60])

    def get_summary(self) -> Dict[str, Any]:
        """Get compressed view of current discussion state."""
        recent = list(self.state.messages)[-10:]
        return {
            "topic": self.state.topic,
            "is_running": self.state.is_running,
            "round": self.state.round_num,
            "last_summary": self.state.last_summary,
            "consensus": self.state.consensus,
            "recent_messages": [m.to_dict() for m in recent],
            "total_messages": len(self.state.messages),
            "duration_s": round(time.time() - self.state.started_at, 1) if self.state.started_at else 0,
        }

    def get_full_log(self) -> List[Dict[str, Any]]:
        """Get the full discussion log."""
        return [m.to_dict() for m in self.state.messages]

    # --- Internal Loop ---

    async def _discussion_loop(self):
        """The main persistent discussion loop."""
        idle_rounds = 0

        try:
            while self.state.is_running:
                self.state.round_num += 1
                self.state.total_rounds += 1
                round_num = self.state.round_num

                # Check for user input (non-blocking)
                user_input = None
                try:
                    user_input = self._user_queue.get_nowait()
                    idle_rounds = 0  # Reset idle counter on user input
                except asyncio.QueueEmpty:
                    pass

                # Build round context
                context = self._build_context(user_input)

                # Each active agent responds
                for agent in self.agents:
                    if not agent.active or not self.state.is_running:
                        continue

                    prompt = self._build_agent_prompt(agent, context, round_num, user_input)
                    system = ROLE_SYSTEM_PROMPTS.get(agent.role, "")

                    try:
                        response = await self._call(prompt, agent.model, system)
                        # Truncate verbose responses
                        if len(response) > 600:
                            response = response[:597] + "..."
                    except Exception as e:
                        response = f"[{agent.role.value} konnte nicht antworten: {e}]"
                        log.warning("Agent %s Fehler: %s", agent.role.value, e)

                    msg = DiscussionMessage(
                        role=agent.role,
                        content=response,
                        round_num=round_num,
                    )
                    self.state.messages.append(msg)
                    await self._notify_listeners(msg)

                # Chief generates round summary every 3 rounds
                if round_num % 3 == 0:
                    summary = await self._generate_summary(final=False)
                    self.state.last_summary = summary
                    msg = DiscussionMessage(
                        role=AgentRole.CHIEF,
                        content=summary,
                        round_num=round_num,
                        is_summary=True,
                    )
                    self.state.messages.append(msg)
                    await self._notify_listeners(msg)

                # Convergence check
                if self._check_convergence():
                    idle_rounds += 1
                    if idle_rounds >= self._max_idle_rounds:
                        log.info("Discussion konvergiert nach %d Idle-Runden — pausiert", idle_rounds)
                        # Don't stop, just slow down
                        await asyncio.sleep(self._round_pause * 3)
                        idle_rounds = 0
                        continue
                else:
                    idle_rounds = 0

                # Pause between rounds (shorter if user input pending)
                pause = 2.0 if not self._user_queue.empty() else self._round_pause
                await asyncio.sleep(pause)

        except asyncio.CancelledError:
            log.info("Discussion-Loop cancelled")
        except Exception as e:
            log.error("Discussion-Loop Fehler: %s", e, exc_info=True)
            self.state.is_running = False

    # --- Helpers ---

    def _build_context(self, user_input: Optional[str] = None) -> str:
        """Build context from recent messages — explicit quotes from each agent."""
        recent = list(self.state.messages)[-6:]
        parts = [f"THEMA: {self.state.topic[:200]}"]
        if self.state.last_summary:
            parts.append(f"BISHERIGER KONSENS: {self.state.last_summary[:200]}")
        parts.append("BISHERIGE DISKUSSION:")
        for m in recent:
            label = m.role.value.upper() if isinstance(m.role, AgentRole) else m.role
            # Truncate but keep meaningful content
            content = m.content[:250].strip()
            parts.append(f'> {label} sagte: "{content}"')
        if user_input:
            parts.append(f'\n> USER fragt: "{user_input}"')
        return "\n".join(parts)

    def _build_agent_prompt(
        self, agent: AgentConfig, context: str,
        round_num: int, user_input: Optional[str] = None,
    ) -> str:
        """Build the prompt for a specific agent — forces direct engagement."""
        role = agent.role.value.upper()

        if round_num == 1:
            return (
                f"{context}\n\n"
                f"Du bist {role}. Runde 1. "
                f"Gib deine Einschaetzung in 2-3 Saetzen. Sei konkret."
            )

        prompt = f"{context}\n\nDu bist {role}. Runde {round_num}."

        if user_input:
            prompt += (
                f'\nDer User fragt: "{user_input}"\n'
                f"Beantworte die Frage direkt in 2-3 Saetzen."
            )
        elif agent.role == AgentRole.CHIEF:
            prompt += (
                "\nFasse in 2 Saetzen zusammen: Was ist Konsens? Was ist noch offen? "
                "Stelle eine konkrete Frage an die Gruppe."
            )
        elif agent.role == AgentRole.ARCHIVIST:
            prompt += (
                "\nPruefe: Widerspricht etwas dem bisherigen Wissen? "
                "Nenne die wichtigste Erkenntnis dieser Runde in einem Satz."
            )
        else:
            prompt += (
                "\nReagiere auf die Aussagen der anderen. "
                "Wo stimmst du zu? Wo widersprichst du? Nenne einen konkreten Punkt."
            )

        return prompt

    def _check_convergence(self) -> bool:
        """Check if the last round showed convergence."""
        recent = list(self.state.messages)[-len(self.agents):]
        if len(recent) < 2:
            return False
        # Simple: check if responses are getting very short (= agreement)
        avg_len = sum(len(m.content) for m in recent) / len(recent)
        # Short responses often mean "ich stimme zu"
        if avg_len < 80:
            return True
        # Word overlap check
        texts = [set(m.content.lower().split()) for m in recent]
        if not all(texts):
            return False
        common = texts[0]
        for t in texts[1:]:
            common &= t
        avg_words = sum(len(t) for t in texts) / len(texts)
        return len(common) / max(avg_words, 1) > 0.35

    async def _generate_summary(self, final: bool = False) -> str:
        """Generate a summary using the Chief agent."""
        chief = next((a for a in self.agents if a.role == AgentRole.CHIEF), None)
        if not chief:
            return ""

        recent = list(self.state.messages)[-12:]
        history = "\n".join(
            f"[{m.role.value if isinstance(m.role, AgentRole) else m.role}]: {m.content[:200]}"
            for m in recent
        )
        kind = "FINALE Zusammenfassung" if final else "Zwischen-Zusammenfassung"
        prompt = (
            f"Thema: {self.state.topic}\n\n"
            f"Diskussion (letzte Beitraege):\n{history}\n\n"
            f"Erstelle eine {kind}:\n"
            f"1. Konsens: Worin sind sich alle einig?\n"
            f"2. Dissens: Wo gibt es noch Unterschiede?\n"
            f"3. Naechste Schritte: Was muss als naechstes passieren?"
        )
        try:
            return await self._call(prompt, chief.model, "Fasse praezise und kurz zusammen.")
        except Exception as e:
            return f"[Zusammenfassung fehlgeschlagen: {e}]"

    async def _call(self, prompt: str, model: str, system: str = "") -> str:
        """Call a model, using injected function or fallback to server."""
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

    async def _notify_listeners(self, msg: DiscussionMessage):
        """Notify all registered listeners of a new message."""
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(msg.to_dict())
                else:
                    listener(msg.to_dict())
            except Exception as e:
                log.debug("Listener notification failed: %s", e)

    # --- Memory Integration ---

    async def save_to_memory(self):
        """Save the current discussion state to Six-Layer Memory."""
        try:
            from core.memory.six_layer_memory import memory
            await memory.store({
                "type": "persistent_discussion",
                "prompt": f"Discussion: {self.state.topic}",
                "response": self.state.consensus or self.state.last_summary,
                "topic": self.state.topic,
                "rounds": self.state.total_rounds,
                "messages": len(self.state.messages),
                "importance": 0.85,
            })
            log.info("Discussion state saved to memory")
        except ImportError:
            log.debug("Six-Layer Memory not available")


# ---------------------------------------------------------------------------
# Global instance + convenience
# ---------------------------------------------------------------------------
discussion = PersistentAgentLoop()


def get_default_inference_agents() -> List[AgentConfig]:
    """Default 4-agent config for Inference Node — SCHNELLE Modelle fuer flüssige Diskussion."""
    return [
        AgentConfig(
            role=AgentRole.CHIEF,
            model="way2agi-consciousness-qwen3",  # 5GB, trainiert
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.REASONER,
            model="nemotron-4b-way2agi-v2",  # 2.7GB, schnell (42 tok/s), trainiert
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.RESEARCHER,
            model="way2agi-orchestrator-qwen3",  # 5GB, trainiert
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.ARCHIVIST,
            model="way2agi-memory-qwen3",  # 5GB, trainiert
            node="inference-node",
        ),
    ]


def get_fast_inference_agents() -> List[AgentConfig]:
    """Schnellste Konfiguration — nur kleine Modelle fuer schnelle Iteration."""
    return [
        AgentConfig(
            role=AgentRole.CHIEF,
            model="nemotron-4b-way2agi-v2",  # 2.7GB, 42 tok/s
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.REASONER,
            model="way2agi-memory-agent-sft",  # 1GB, ultra-schnell
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.RESEARCHER,
            model="mannix/smallthinker-abliterated",  # 1.8GB, schnell
            node="inference-node",
        ),
        AgentConfig(
            role=AgentRole.ARCHIVIST,
            model="way2agi-memory-qwen3",  # 5GB, trainiert
            node="inference-node",
        ),
    ]
