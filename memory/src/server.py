"""
Way2AGI Memory Server — FastAPI bridge between TS cognitive core and Python ML layer.

Exposes the 4-tier memory system backed by elias-memory:
- Episodic Buffer (working memory, in-memory with auto-eviction)
- Episodic Memory (events + outcomes, persisted via elias-memory)
- Semantic Memory (facts + concepts via elias-memory vector search)
- Procedural Memory (skill traces, persisted via elias-memory)

Plus: World Model queries, Knowledge Gap detection, Consolidation triggers.
"""

from __future__ import annotations

import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from elias_memory import Memory, MemoryRecord
from .logger import create_logger

# Optional telemetry (available in Docker, graceful skip on mobile)
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from telemetry.setup import init_telemetry
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    _HAS_TELEMETRY = True
except ImportError:
    _HAS_TELEMETRY = False

log = create_logger("memory-server")

# --- Request/Response Models ---


class MemoryQueryReq(BaseModel):
    query: str
    top_k: int = 5
    memory_type: str = "semantic"  # semantic | episodic | procedural | buffer
    context: dict[str, Any] | None = None


class MemoryStoreReq(BaseModel):
    content: str
    memory_type: str = "episodic"
    metadata: dict[str, Any] | None = None
    importance: float = 0.5


class KnowledgeGap(BaseModel):
    topic: str
    coverage: float


class SkillRate(BaseModel):
    skill: str
    rate: float


class Pattern(BaseModel):
    pattern: str
    confidence: float


class ConsolidationResult(BaseModel):
    episodes_processed: int
    lessons_extracted: int
    memories_pruned: int


# --- Persistent store (elias-memory) + ephemeral buffer ---

DB_PATH = os.environ.get("MEMORY_DB_PATH", "data/way2agi_memory.db")
_memory: Memory | None = None
_buffer: deque[dict[str, Any]] = deque(maxlen=50)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize elias-memory backend."""
    global _memory
    print(f"[Memory] Starting Way2AGI Memory Server (db: {DB_PATH})")
    log.info("server starting", extra={"metadata": {"db_path": DB_PATH}})
    _memory = Memory(DB_PATH)
    log.info("memories loaded", extra={"metadata": {"count": len(_memory._records)}})
    print(f"[Memory] Loaded {len(_memory._records)} existing memories")
    yield
    if _memory:
        _memory.close()
    log.info("server shutdown")
    print("[Memory] Shutting down Memory Server")


app = FastAPI(
    title="Way2AGI Memory Server",
    version="0.3.0",
    lifespan=lifespan,
)

# Auto-instrument with OpenTelemetry if available
if _HAS_TELEMETRY:
    init_telemetry("way2agi-memory")
    FastAPIInstrumentor.instrument_app(app)


def _get_memory() -> Memory:
    assert _memory is not None, "Memory not initialized"
    return _memory


# --- Map Way2AGI 4-tier types to elias-memory 2 types (v1) ---
# episodic + buffer + procedural -> "episodic" in elias-memory
# semantic -> "semantic" in elias-memory
# The memory_type is preserved in metadata for filtering

def _to_elias_type(memory_type: str) -> str:
    return "semantic" if memory_type == "semantic" else "episodic"


@app.get("/health")
async def health():
    mem = _get_memory()
    type_counts: dict[str, int] = {}
    for rec in mem._records.values():
        mt = rec.metadata.get("way2agi_type", rec.type)
        type_counts[mt] = type_counts.get(mt, 0) + 1
    return {
        "status": "ok",
        "version": "0.3.0",
        "backend": "elias-memory v0.1.0",
        "total_memories": len(mem._records),
        "buffer_size": len(_buffer),
        "stores": type_counts,
    }


@app.post("/memory/store")
async def store_memory(req: MemoryStoreReq):
    """Store a new memory entry."""
    mem = _get_memory()

    # Buffer is ephemeral (in-memory only)
    if req.memory_type == "buffer":
        entry = {
            "content": req.content,
            "type": "buffer",
            "metadata": req.metadata or {},
            "importance": req.importance,
            "timestamp": datetime.now().isoformat(),
        }
        _buffer.append(entry)
        log.info("memory stored", extra={"metadata": {"memory_type": "buffer", "buffer_size": len(_buffer)}})
        return {"stored": True, "type": "buffer", "buffer_size": len(_buffer)}

    # All other types go to elias-memory
    metadata = req.metadata or {}
    metadata["way2agi_type"] = req.memory_type
    metadata["timestamp"] = datetime.now().isoformat()

    mid = mem.add(
        req.content,
        type=_to_elias_type(req.memory_type),
        importance=req.importance,
        metadata=metadata,
    )

    log.info("memory stored", extra={"metadata": {"memory_type": req.memory_type, "id": mid, "total": len(mem._records)}})
    return {"stored": True, "type": req.memory_type, "id": mid, "total": len(mem._records)}


@app.post("/memory/query")
async def query_memory(req: MemoryQueryReq) -> list[dict[str, Any]]:
    """Query memories using vector search via elias-memory."""
    mem = _get_memory()

    # Buffer queries are simple keyword search (ephemeral)
    if req.memory_type == "buffer":
        results = []
        query_lower = req.query.lower()
        for entry in reversed(_buffer):
            if query_lower in entry["content"].lower():
                results.append(entry)
                if len(results) >= req.top_k:
                    break
        return results

    # Vector search via elias-memory
    all_results = mem.recall(req.query, top_k=req.top_k * 3)

    # Filter by way2agi_type
    filtered = []
    for rec in all_results:
        way2agi_type = rec.metadata.get("way2agi_type", rec.type)
        if req.memory_type == "all" or way2agi_type == req.memory_type:
            filtered.append({
                "id": rec.id,
                "content": rec.content,
                "type": way2agi_type,
                "importance": rec.importance,
                "metadata": rec.metadata,
                "created_at": rec.created_at.isoformat(),
                "access_count": rec.access_count,
            })
            if len(filtered) >= req.top_k:
                break

    log.info("memory queried", extra={"metadata": {"memory_type": req.memory_type, "results": len(filtered)}})
    return filtered


@app.post("/memory/reinforce/{memory_id}")
async def reinforce_memory(memory_id: str):
    """Reinforce a memory (increases access count, delays decay)."""
    mem = _get_memory()
    mem.reinforce(memory_id)
    return {"reinforced": True, "id": memory_id}


@app.get("/memory/knowledge-gaps")
async def knowledge_gaps() -> list[KnowledgeGap]:
    """Detect topics with low coverage — feeds the Curiosity Drive."""
    mem = _get_memory()
    topics: dict[str, int] = {}
    for rec in mem._records.values():
        topic = rec.metadata.get("topic", "general")
        topics[topic] = topics.get(topic, 0) + 1

    if not topics:
        return [KnowledgeGap(topic="self-improvement", coverage=0.1)]

    max_count = max(topics.values())
    return [
        KnowledgeGap(topic=t, coverage=min(1.0, c / max_count))
        for t, c in sorted(topics.items(), key=lambda x: x[1])
    ]


@app.get("/memory/skill-rates")
async def skill_rates() -> list[SkillRate]:
    """Get skill success rates — feeds the Competence Drive."""
    mem = _get_memory()
    skills: dict[str, dict[str, int]] = {}
    for rec in mem._records.values():
        if rec.metadata.get("way2agi_type") != "procedural":
            continue
        skill = rec.metadata.get("skill", "unknown")
        success = rec.metadata.get("success", False)
        if skill not in skills:
            skills[skill] = {"total": 0, "success": 0}
        skills[skill]["total"] += 1
        if success:
            skills[skill]["success"] += 1

    return [
        SkillRate(skill=s, rate=d["success"] / d["total"] if d["total"] > 0 else 0.0)
        for s, d in skills.items()
    ]


@app.get("/memory/patterns")
async def recent_patterns() -> list[Pattern]:
    """Detect interaction patterns — feeds the Social Drive and Reflection."""
    mem = _get_memory()

    # Analyze recurring topics in recent memories
    topic_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    total = 0

    for rec in mem._records.values():
        total += 1
        # Track topics
        topic = rec.metadata.get("topic", "")
        if topic:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

        # Track error patterns
        if rec.metadata.get("is_error") or "fehler" in rec.content.lower() or "error" in rec.content.lower():
            error_type = rec.metadata.get("error_type", "unclassified")
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

        # Track operation patterns from way2agi_type
        way2agi_type = rec.metadata.get("way2agi_type", "")
        if way2agi_type:
            topic_counts[f"type:{way2agi_type}"] = topic_counts.get(f"type:{way2agi_type}", 0) + 1

    patterns = []

    # Frequent topics as patterns
    if total > 0:
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1])[:5]:
            confidence = min(1.0, count / max(total * 0.1, 1))
            if confidence > 0.1:
                patterns.append(Pattern(
                    pattern=f"Frequent topic: {topic} ({count}x)",
                    confidence=round(confidence, 2),
                ))

    # Recurring errors as patterns
    for error_type, count in sorted(error_counts.items(), key=lambda x: -x[1])[:3]:
        if count >= 2:
            patterns.append(Pattern(
                pattern=f"Recurring error: {error_type} ({count}x)",
                confidence=min(1.0, count / 5),
            ))

    # Memory type distribution pattern
    type_dist = {}
    for rec in mem._records.values():
        t = rec.type
        type_dist[t] = type_dist.get(t, 0) + 1
    if type_dist:
        dominant = max(type_dist, key=type_dist.get)
        ratio = type_dist[dominant] / total if total > 0 else 0
        if ratio > 0.7:
            patterns.append(Pattern(
                pattern=f"Memory imbalance: {ratio:.0%} are {dominant} type",
                confidence=ratio,
            ))

    return patterns


@app.post("/memory/consolidate")
async def consolidate() -> ConsolidationResult:
    """Consolidation: episodes -> lessons -> semantic/procedural.

    Groups recent episodes, extracts lessons via LLM (Jetson or Desktop),
    and stores them as semantic memories with higher importance.
    """
    mem = _get_memory()

    # Find unconsolidated episodic memories
    episodes = [
        rec for rec in mem._records.values()
        if rec.metadata.get("way2agi_type") == "episodic"
        and not rec.metadata.get("consolidated")
    ]

    processed = 0
    lessons = 0

    # Group episodes in batches of 5 for lesson extraction
    batch_size = 5
    for i in range(0, len(episodes), batch_size):
        batch = episodes[i : i + batch_size]
        contents = [f"- {rec.content}" for rec in batch]
        batch_text = "\n".join(contents)

        # Try to extract lessons via LLM
        lesson = await _extract_lesson(batch_text)

        if lesson:
            # Store lesson as semantic memory with high importance
            mem.add(
                lesson,
                type="semantic",
                importance=0.8,
                metadata={
                    "way2agi_type": "semantic",
                    "source": "consolidation",
                    "episode_count": len(batch),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            lessons += 1

        # Mark episodes as consolidated
        for rec in batch:
            rec.metadata["consolidated"] = True
            processed += 1

    # Run decay cycle
    mem.decay_cycle()

    # Count prunable memories (importance at floor)
    prunable = sum(1 for r in mem._records.values() if r.importance <= 0.02)

    log.info("consolidation complete", extra={"metadata": {
        "episodes_processed": processed,
        "lessons_extracted": lessons,
        "memories_pruned": prunable,
    }})
    return ConsolidationResult(
        episodes_processed=processed,
        lessons_extracted=lessons,
        memories_pruned=prunable,
    )


async def _extract_lesson(episodes_text: str) -> str | None:
    """Extract a lesson from a batch of episodes using an available LLM.

    Tries: Jetson (local, free) -> Desktop daemon -> fallback heuristic.
    """
    import json
    import urllib.request
    import urllib.error

    prompt = (
        "Du bist ein Reflexions-Agent. Analysiere diese Episoden und extrahiere "
        "EINE zentrale Erkenntnis oder Lektion daraus. Antworte NUR mit der Lektion "
        "als ein praegnanter Satz. Kein JSON, kein Markdown.\n\n"
        f"Episoden:\n{episodes_text}"
    )

    # Try Jetson first (always-on, free)
    endpoints = [
        ("http://YOUR_CONTROLLER_IP:11434", "huihui_ai/qwen3-abliterated:8b"),
        ("http://YOUR_DESKTOP_IP:11434", "qwen3.5:9b"),
    ]

    for base_url, model in endpoints:
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": "Extrahiere Lektionen. Antworte kurz und praegnant. /no_think"},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": 200, "temperature": 0.3},
            }).encode()
            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                content = data.get("message", {}).get("content", "").strip()
                if content and len(content) > 10:
                    log.info("lesson extracted", extra={"metadata": {"model": model, "length": len(content)}})
                    return content
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue

    # Fallback: simple heuristic (first episode as-is)
    if episodes_text.strip():
        lines = episodes_text.strip().split("\n")
        if lines:
            return f"[auto-consolidation] {lines[0].lstrip('- ').strip()}"
    return None


@app.post("/memory/export-sft")
async def export_sft(path: str = "data/sft_export.jsonl"):
    """Export all memories as SFT training data."""
    # Security: prevent path traversal
    EXPORT_ROOT = os.path.realpath("data")
    resolved = os.path.realpath(path)
    if not resolved.startswith(EXPORT_ROOT + os.sep) and resolved != EXPORT_ROOT:
        return {"error": "Invalid path: must be within data/ directory", "exported": 0}
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    mem = _get_memory()
    mem.export_sft(resolved)
    return {"exported": len(mem._records), "path": resolved}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
