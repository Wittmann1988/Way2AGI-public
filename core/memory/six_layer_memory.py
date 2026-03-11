# core/memory/six_layer_memory.py
"""
Way2AGI Six-Layer Memory System
================================
Integriert & verbessert: Mem0 + Zep + Letta + EM-LLM + Cognee
+ Consciousness-, Evolution- und Workflow-Features

Layer 1: Raw Episodic Events (EM-LLM Style)
Layer 2: Vector Similarity (Mem0 / Zep)
Layer 3: Knowledge Graph (Cognee)
Layer 4: Symbolic Rules & Goals (Letta)
Layer 5: Reflective Summaries (Consciousness Layer)
Layer 6: Immutable Identity & Workflow Models
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from core.config import config
except ImportError:
    config = None  # type: ignore[assignment]

log = logging.getLogger("way2agi.memory")


class SixLayerMemory:
    """Das Herz des Memory-Systems — orchestriert alle 6 Layer."""

    def __init__(self):
        self.layers = {
            1: "Raw Episodic Events",
            2: "Vector Similarity",
            3: "Knowledge Graph",
            4: "Symbolic Rules & Goals",
            5: "Reflective Summaries",
            6: "Immutable Identity & Workflow Models",
        }
        self.identity = None  # wird in identity_core.py geladen
        self._last_evolution_check = 0.0
        self._evolution_interval = 86400  # 24h

        # Layer backends (lazy init)
        self._episodic = None
        self._vector = None
        self._graph = None
        self._symbolic = None
        self._reflection = None
        self._identity_core = None

    async def initialize(self):
        """Lazy-Init aller Layer-Backends."""
        try:
            from core.memory.episodic_engine import EpisodicEngine
            self._episodic = EpisodicEngine()
            log.info("Layer 1 (Episodic): initialized")
        except Exception as e:
            log.warning("Layer 1 (Episodic): not available — %s", e)

        try:
            from core.memory.hybrid_store import HybridStore
            self._vector = HybridStore()
            log.info("Layer 2+3 (Vector+Graph): initialized")
        except Exception as e:
            log.warning("Layer 2+3 (Vector+Graph): not available — %s", e)

        try:
            from core.memory.identity_core import IdentityCore
            self._identity_core = IdentityCore()
            self.identity = await self._identity_core.load()
            log.info("Layer 6 (Identity): loaded")
        except Exception as e:
            log.warning("Layer 6 (Identity): not available — %s", e)

        log.info("Six-Layer Memory initialized (%d layers description loaded)", len(self.layers))

    async def store(self, interaction: Dict[str, Any]):
        """Speichert eine Interaktion in allen 6 Layern."""
        timestamp = interaction.get("timestamp", time.time())
        interaction["timestamp"] = timestamp

        # Layer 1 — Raw Event
        await self._store_episodic(interaction)

        # Layer 2 — Vector
        await self._store_vector(interaction)

        # Layer 3 — Graph
        await self._store_graph(interaction)

        # Layer 4 — Rules & Goals
        await self._store_symbolic(interaction)

        # Layer 5 — Consciousness Reflection
        consciousness_enabled = config.ENABLE_CONSCIOUSNESS if config else False
        if consciousness_enabled:
            await self._reflect_and_summarize(interaction)

        # Layer 6 — Identity & Workflow Training
        await self._update_identity_and_train_workflow(interaction)

        # Trigger taegliche Evolution (wenn noetig)
        await self._check_daily_evolution()

    async def recall(self, query: str, top_k: int = 5) -> List[Dict]:
        """Holt die relevantesten Erinnerungen ueber alle 6 Layer."""
        results: List[Dict] = []

        # Layer 2 — Vector similarity search
        if self._vector:
            try:
                vector_results = await self._vector.search(query, top_k=top_k)
                results.extend(vector_results)
            except Exception as e:
                log.debug("Vector recall failed: %s", e)

        # Layer 1 — Recent episodic events
        if self._episodic:
            try:
                episodic_results = await self._episodic.recall_recent(query, limit=top_k)
                results.extend(episodic_results)
            except Exception as e:
                log.debug("Episodic recall failed: %s", e)

        # Layer 6 — Identity context
        if self._identity_core and self.identity:
            results.append({
                "layer": 6,
                "type": "identity",
                "content": self.identity,
                "relevance": 1.0,
            })

        # Deduplicate and sort by relevance
        seen = set()
        unique_results = []
        for r in results:
            key = r.get("content", str(r))[:200]
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        unique_results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return unique_results[:top_k]

    # === Layer implementations (stubs — erweitert durch Backend-Module) ===

    async def _store_episodic(self, interaction: Dict[str, Any]):
        """Layer 1: Raw event storage."""
        if self._episodic:
            try:
                await self._episodic.store(interaction)
            except Exception as e:
                log.debug("Episodic store failed: %s", e)

    async def _store_vector(self, interaction: Dict[str, Any]):
        """Layer 2: Vector embedding storage."""
        if self._vector:
            try:
                await self._vector.store_vector(interaction)
            except Exception as e:
                log.debug("Vector store failed: %s", e)

    async def _store_graph(self, interaction: Dict[str, Any]):
        """Layer 3: Knowledge graph update."""
        if self._vector:
            try:
                await self._vector.store_graph(interaction)
            except Exception as e:
                log.debug("Graph store failed: %s", e)

    async def _store_symbolic(self, interaction: Dict[str, Any]):
        """Layer 4: Rules & goals extraction."""
        # Extracts rules/goals from interaction if detected
        content = interaction.get("prompt", "") + " " + interaction.get("response", "")
        rule_keywords = ["immer", "nie", "regel", "always", "never", "rule", "goal", "ziel"]
        if any(kw in content.lower() for kw in rule_keywords):
            log.debug("Layer 4: Potential rule/goal detected in interaction")

    async def _reflect_and_summarize(self, interaction: Dict[str, Any]):
        """Layer 5: Consciousness reflection."""
        try:
            from core.memory.reflection_agent import reflect_on_interaction
            await reflect_on_interaction(interaction)
        except ImportError:
            log.debug("Reflection agent not available")

    async def _update_identity_and_train_workflow(self, interaction: Dict[str, Any]):
        """Layer 6: Identity preservation + workflow learning."""
        if self._identity_core:
            try:
                await self._identity_core.update_from_interaction(interaction)
            except Exception as e:
                log.debug("Identity update failed: %s", e)

    async def _check_daily_evolution(self):
        """Selbstverbesserungspipeline — laeuft taeglich."""
        now = time.time()
        if now - self._last_evolution_check < self._evolution_interval:
            return
        self._last_evolution_check = now

        try:
            from core.memory.proactive_extractor import ingest_new_research
            await ingest_new_research()
            log.info("Daily Evolution: Memory wurde verbessert")
        except ImportError:
            log.debug("Proactive extractor not available yet")
        except Exception as e:
            log.warning("Daily evolution failed: %s", e)


# Globale Instanz
memory = SixLayerMemory()
