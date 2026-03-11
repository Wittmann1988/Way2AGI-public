# Self-Improving Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Geschlossener Self-Improvement Loop in Way2AGI: Alle Agenten (Forge, Sidekick, HackerAI) sammeln Traces, bewerten Aktionen, trainieren Modelle und deployen Verbesserungen — automatisch.

**Architecture:** Way2AGI wird zur zentralen Pipeline. Neue Module `pipeline/` (Trace Collector + Evaluator + Training Trigger) und `training/` (SFT/DPO Runner + GGUF Converter + Deployer) ergaenzen die existierenden Module. elias-memory ist das einzige Memory-Backend. Agent Forge und Sidekick werden zu Trace-Quellen degradiert — ihre eigene Memory-Logik entfaellt.

**Tech Stack:** Python 3.13, httpx, elias-memory, HuggingFace Hub API, Ollama API. Existierende Way2AGI Module: research/src/training_data.py (Multi-Modell Caller), research/src/pipeline.py (Research Loop), memory/src/server.py (FastAPI bridge).

**Existierender Code der wiederverwendet wird:**
- `research/src/training_data.py` — call_model(), _PROVIDER_CALLERS, TRAINING_PROMPTS
- `elias-memory/scripts/generate_traces.py` — Multi-Provider Trace Generation
- `elias-memory/scripts/train_sft.py` — HF Jobs SFT Training
- `Way2AGI/scripts/convert_gguf.py` — GGUF Conversion

---

## Phase A: Bugfixes (kritische Bugs aus Code Review)

### Task 1: Fix Agent Forge Linear Decay Bug

**Files:**
- Modify: `~/agent-forge/loop-agent/index.js` (decayMemories function)

**Step 1: Fix decay from linear to exponential**

Replace:
```js
function decayMemories(db) {
  db.run(`UPDATE memories SET confidence = MAX(0.0, confidence - 0.02)
          WHERE updated_at < datetime('now', '-3 days')
          AND category NOT IN ('preference', 'fact')`);
  db.run("DELETE FROM memories WHERE confidence <= 0.0");
}
```

With:
```js
function decayMemories(db) {
  // Exponential decay: half-life 7 days = factor 0.9961 per 5-min cycle
  // 0.5 = x^(7*24*12) → x = 0.5^(1/2016) ≈ 0.99966
  db.run(`UPDATE memories SET confidence = MAX(0.01, confidence * 0.99966)
          WHERE category NOT IN ('preference', 'fact')`);
  db.run("DELETE FROM memories WHERE confidence <= 0.01");
}
```

**Step 2: Verify** — Run: `node ~/agent-forge/cli.js health`

**Step 3: Commit**
```bash
cd ~/agent-forge && git add loop-agent/index.js && git commit -m "fix: exponential decay instead of linear (was killing memories in 85min)"
```

---

### Task 2: Fix Agent Forge git add -A Security Risk

**Files:**
- Modify: `~/agent-forge/loop-agent/index.js` (syncToGitHub function)

**Step 1: Replace git add -A with specific paths**

Replace:
```js
execSync(`cd ${forgeDir} && git add -A && git diff --cached --quiet || git commit -m "sync: task update $(date +%Y%m%d-%H%M)" && git push 2>/dev/null`, { stdio: "pipe" });
```

With:
```js
execSync(`cd ${forgeDir} && git add tasks/ data/memory-summary.json projects.json 2>/dev/null && git diff --cached --quiet || git commit -m "sync: task update $(date +%Y%m%d-%H%M)" && git push 2>/dev/null`, { stdio: "pipe" });
```

**Step 2: Ensure .gitignore exists**
```bash
echo -e "*.db\n.env\nnode_modules/\n*.sqlite\n*.sqlite3" >> ~/agent-forge/.gitignore
```

**Step 3: Commit**
```bash
cd ~/agent-forge && git add .gitignore loop-agent/index.js && git commit -m "fix: prevent git add -A from committing secrets"
```

---

### Task 3: Fix Agent Forge Cycle Overlap

**Files:**
- Modify: `~/agent-forge/loop-agent/index.js` (main function)

**Step 1: Replace setInterval with sequential loop**

Replace:
```js
async function main() {
  // ...startup...
  await runCycle();
  setInterval(runCycle, LOOP_INTERVAL);
}
```

With:
```js
async function main() {
  // ...startup...
  while (true) {
    await runCycle();
    await new Promise(resolve => setTimeout(resolve, LOOP_INTERVAL));
  }
}
```

**Step 2: Commit**
```bash
cd ~/agent-forge && git add loop-agent/index.js && git commit -m "fix: prevent cycle overlap with sequential loop"
```

---

### Task 4: Fix elias-memory numpy overflow

**Files:**
- Modify: `~/repos/elias-memory/src/elias_memory/store/vec.py`

**Step 1: Cast to float32 before matmul**

Find the line:
```python
similarities = matrix @ q
```

Replace with:
```python
similarities = matrix.astype(np.float32) @ q.astype(np.float32)
```

**Step 2: Run tests**
```bash
cd ~/repos/elias-memory && python3 -m pytest tests/ -v
```

**Step 3: Commit**
```bash
cd ~/repos/elias-memory && git add src/elias_memory/store/vec.py && git commit -m "fix: cast to float32 to prevent numpy overflow in hash embeddings"
```

---

## Phase B: Trace Collection (Way2AGI pipeline/ Modul)

### Task 5: Create Trace Collector Module

**Files:**
- Create: `~/repos/Way2AGI/pipeline/__init__.py`
- Create: `~/repos/Way2AGI/pipeline/collector.py`
- Create: `~/repos/Way2AGI/pipeline/schema.py`
- Test: `~/repos/Way2AGI/pipeline/tests/test_collector.py`

**Step 1: Write trace schema**

```python
# pipeline/schema.py
"""Trace schema for the self-improving pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
import json
import uuid

@dataclass
class Trace:
    """A single agent action trace."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent: str = ""          # "forge", "sidekick", "claude", "hackerai"
    action: str = ""         # "task_decompose", "code_review", "memory_store", etc.
    input: str = ""          # The prompt/request
    output: str = ""         # The response/result
    model: str = ""          # Which model was used
    provider: str = ""       # "groq", "openrouter", "ollama", etc.
    success: bool = True
    duration_ms: int = 0
    score: float = 0.0       # 0-1, filled by evaluator
    evaluator: str = ""      # Which model scored this
    domain: str = ""         # "code", "research", "memory", "reasoning"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_sft(self) -> dict:
        """Convert to HF Chat format for SFT training."""
        return {
            "messages": [
                {"role": "user", "content": self.input},
                {"role": "assistant", "content": self.output},
            ],
            "metadata": {
                "agent": self.agent,
                "model": self.model,
                "score": self.score,
                "domain": self.domain,
            },
        }

    def to_dpo_pair(self, rejected_output: str) -> dict:
        """Convert to DPO format (needs a rejected response)."""
        return {
            "prompt": self.input,
            "chosen": self.output,
            "rejected": rejected_output,
        }
```

**Step 2: Write collector**

```python
# pipeline/collector.py
"""Trace Collector — stores traces in elias-memory + JSONL files."""
from __future__ import annotations
import json
import os
from pathlib import Path
from elias_memory import Memory
from .schema import Trace

TRACE_DB = os.environ.get("TRACE_DB", os.path.expanduser("~/.config/ai-manager/traces.db"))
TRACE_JSONL = os.environ.get("TRACE_JSONL", os.path.expanduser("~/.way2agi/traces/traces.jsonl"))

class TraceCollector:
    def __init__(self, db_path: str = TRACE_DB, jsonl_path: str = TRACE_JSONL):
        self._mem = Memory(db_path)
        self._jsonl = Path(jsonl_path)
        self._jsonl.parent.mkdir(parents=True, exist_ok=True)

    def collect(self, trace: Trace) -> str:
        """Store a trace in elias-memory and append to JSONL."""
        mid = self._mem.add(
            content=f"[{trace.agent}/{trace.action}] {trace.input[:200]}",
            type="episodic",
            importance=max(0.3, trace.score) if trace.score > 0 else 0.5,
            metadata={
                "trace_id": trace.id,
                "agent": trace.agent,
                "action": trace.action,
                "model": trace.model,
                "success": trace.success,
                "score": trace.score,
                "domain": trace.domain,
            },
        )
        with open(self._jsonl, "a") as f:
            f.write(trace.to_jsonl() + "\n")
        return mid

    def query(self, search: str, top_k: int = 10) -> list[dict]:
        """Search traces by content."""
        results = self._mem.recall(search, top_k=top_k)
        return [{"id": r.id, "content": r.content, "metadata": r.metadata} for r in results]

    def count(self) -> int:
        return len(self._mem._records)

    def export_sft(self, min_score: float = 0.6, output: str | None = None) -> Path:
        """Export high-quality traces as SFT JSONL."""
        out = Path(output or self._jsonl.parent / "sft_export.jsonl")
        traces = []
        with open(self._jsonl) as f:
            for line in f:
                t = json.loads(line)
                if t.get("score", 0) >= min_score and t.get("success", False):
                    traces.append({
                        "messages": [
                            {"role": "user", "content": t["input"]},
                            {"role": "assistant", "content": t["output"]},
                        ]
                    })
        with open(out, "w") as f:
            for t in traces:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        return out

    def close(self):
        self._mem.close()
```

**Step 3: Write test**

```python
# pipeline/tests/test_collector.py
import tempfile, os
from pipeline.collector import TraceCollector
from pipeline.schema import Trace

def test_collect_and_query():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        jsonl = os.path.join(d, "traces.jsonl")
        c = TraceCollector(db_path=db, jsonl_path=jsonl)

        t = Trace(agent="test", action="review", input="Review this code", output="Looks good", score=0.8, success=True)
        mid = c.collect(t)
        assert mid
        assert c.count() == 1
        assert os.path.exists(jsonl)
        c.close()

def test_export_sft_filters_low_score():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        jsonl = os.path.join(d, "traces.jsonl")
        c = TraceCollector(db_path=db, jsonl_path=jsonl)

        c.collect(Trace(agent="a", action="x", input="hi", output="ho", score=0.9, success=True))
        c.collect(Trace(agent="a", action="x", input="lo", output="no", score=0.2, success=False))
        out = c.export_sft(min_score=0.6)
        with open(out) as f:
            lines = f.readlines()
        assert len(lines) == 1  # Only the high-score trace
        c.close()
```

**Step 4: Run tests**
```bash
cd ~/repos/Way2AGI && python3 -m pytest pipeline/tests/test_collector.py -v
```

**Step 5: Commit**
```bash
cd ~/repos/Way2AGI && git add pipeline/ && git commit -m "feat: add trace collector module for self-improving pipeline"
```

---

### Task 6: Create Evaluator Module

**Files:**
- Create: `~/repos/Way2AGI/pipeline/evaluator.py`
- Test: `~/repos/Way2AGI/pipeline/tests/test_evaluator.py`

**Step 1: Write evaluator (uses multiple models to score traces)**

```python
# pipeline/evaluator.py
"""Multi-model evaluator — scores traces using available LLMs."""
from __future__ import annotations
import asyncio
import statistics
from research.src.training_data import call_model
from .schema import Trace

EVAL_SYSTEM = """You are a quality evaluator for AI agent actions.
Score the following agent response on a scale of 0.0 to 1.0.
Consider: correctness, helpfulness, efficiency, safety.
Return ONLY a JSON object: {"score": 0.X, "reason": "brief explanation"}"""

EVAL_MODELS = [
    {"id": "llama-3.3-70b-versatile", "provider": "groq"},
    {"id": "google/gemma-3-4b-it:free", "provider": "openrouter"},
]

async def evaluate_trace(trace: Trace, models: list[dict] | None = None) -> Trace:
    """Score a trace using multiple models. Returns trace with score filled."""
    models = models or EVAL_MODELS
    prompt = f"""Agent: {trace.agent}
Action: {trace.action}
Input: {trace.input[:500]}
Output: {trace.output[:1000]}
Success: {trace.success}

Score this response (0.0-1.0):"""

    scores = []
    for m in models:
        resp = await call_model(m["id"], m["provider"], EVAL_SYSTEM, prompt)
        if resp:
            try:
                import json
                data = json.loads(resp[resp.find("{"):resp.rfind("}")+1])
                s = float(data.get("score", 0))
                if 0 <= s <= 1:
                    scores.append(s)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    if scores:
        trace.score = round(statistics.mean(scores), 3)
        trace.evaluator = ",".join(m["id"].split("/")[-1] for m in models[:len(scores)])
    return trace

async def evaluate_batch(traces: list[Trace], concurrency: int = 3) -> list[Trace]:
    """Evaluate multiple traces with rate limiting."""
    sem = asyncio.Semaphore(concurrency)
    async def _eval(t):
        async with sem:
            return await evaluate_trace(t)
    return await asyncio.gather(*[_eval(t) for t in traces])
```

**Step 2: Write test**

```python
# pipeline/tests/test_evaluator.py
from pipeline.schema import Trace

def test_trace_schema():
    t = Trace(agent="forge", action="decompose", input="Fix bug", output="Here are 3 subtasks")
    assert t.agent == "forge"
    sft = t.to_sft()
    assert sft["messages"][0]["role"] == "user"
    assert sft["messages"][1]["content"] == "Here are 3 subtasks"
```

**Step 3: Commit**
```bash
cd ~/repos/Way2AGI && git add pipeline/evaluator.py pipeline/tests/test_evaluator.py && git commit -m "feat: add multi-model evaluator for trace scoring"
```

---

## Phase C: Training Loop Integration

### Task 7: Create Training Trigger Module

**Files:**
- Create: `~/repos/Way2AGI/pipeline/trainer.py`

**Step 1: Write trainer that combines existing scripts**

```python
# pipeline/trainer.py
"""Training Trigger — checks if enough traces, starts HF Jobs training."""
from __future__ import annotations
import json
import os
from pathlib import Path

TRACE_JSONL = Path(os.environ.get("TRACE_JSONL", os.path.expanduser("~/.way2agi/traces/traces.jsonl")))
MIN_TRACES_FOR_TRAINING = int(os.environ.get("MIN_TRACES", "50"))
HF_DATASET_ID = "YOUR_HF_USER/way2agi-traces"

def check_training_ready() -> dict:
    """Check if we have enough scored traces to trigger training."""
    if not TRACE_JSONL.exists():
        return {"ready": False, "reason": "no traces file", "count": 0}

    scored = 0
    total = 0
    with open(TRACE_JSONL) as f:
        for line in f:
            total += 1
            t = json.loads(line)
            if t.get("score", 0) >= 0.6 and t.get("success"):
                scored += 1

    return {
        "ready": scored >= MIN_TRACES_FOR_TRAINING,
        "total_traces": total,
        "scored_traces": scored,
        "threshold": MIN_TRACES_FOR_TRAINING,
    }

def push_to_hf(sft_path: Path, dataset_id: str = HF_DATASET_ID) -> str:
    """Push SFT JSONL to HuggingFace Dataset."""
    from huggingface_hub import HfApi
    api = HfApi()
    api.upload_file(
        path_or_fileobj=str(sft_path),
        path_in_repo="train.jsonl",
        repo_id=dataset_id,
        repo_type="dataset",
    )
    return f"https://huggingface.co/datasets/{dataset_id}"
```

**Step 2: Commit**
```bash
cd ~/repos/Way2AGI && git add pipeline/trainer.py && git commit -m "feat: add training trigger with HF Hub push"
```

---

### Task 8: Wire Sidekick Trace Collection

**Files:**
- Modify: `~/ollama-sidekick/src/index.ts`

**Step 1: Add trace logging to every sidekick request**

After each model call, append a trace JSONL line via a simple HTTP POST to the trace collector or write directly to the JSONL file.

This needs a small Python HTTP endpoint or a simple file append from Node. Simplest: write JSONL directly.

Add to sidekick after each response:
```typescript
// At top of file:
import { appendFileSync, mkdirSync } from 'fs';
const TRACE_FILE = process.env.TRACE_JSONL || `${process.env.HOME}/.way2agi/traces/traces.jsonl`;
try { mkdirSync(new URL('file://' + TRACE_FILE).pathname.replace(/\/[^/]+$/, ''), { recursive: true }); } catch {}

function logTrace(agent: string, action: string, input: string, output: string, model: string, provider: string, durationMs: number) {
  const trace = JSON.stringify({
    id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    agent, action, input: input.slice(0, 2000), output: output.slice(0, 2000),
    model, provider, success: true, duration_ms: durationMs,
    score: 0, evaluator: "", domain: "", metadata: {},
  });
  try { appendFileSync(TRACE_FILE, trace + '\n'); } catch {}
}
```

Then call `logTrace()` after each sidekick_ask/review/analyze/research response.

**Step 2: Commit**
```bash
cd ~/ollama-sidekick && git add src/index.ts && git commit -m "feat: add trace logging for self-improving pipeline"
```

---

## Phase D: Benchmark Durchlaeufe (3x Konzept-Iteration)

### Task 9: Durchlauf 1 — Baseline Benchmark

**Run all Sidekick models against our code, collect traces, evaluate:**
```bash
cd ~/repos/Way2AGI && python3 -c "
import asyncio
from pipeline.collector import TraceCollector
from pipeline.evaluator import evaluate_trace
from pipeline.schema import Trace
from research.src.training_data import call_model

# ... run code review against all code, collect traces, evaluate
"
```

Save results as `~/.way2agi/benchmarks/run-1-baseline.json`

### Task 10: Durchlauf 2 — Nach Bugfixes

Re-run same benchmark after Phase A bugfixes applied.
Save as `~/.way2agi/benchmarks/run-2-post-fixes.json`

### Task 11: Durchlauf 3 — Nach Pipeline Integration

Re-run after Phases B+C implemented.
Save as `~/.way2agi/benchmarks/run-3-pipeline.json`

Compare all 3 runs: code quality score, trace count, evaluation accuracy.

---

## Zusammenfassung

| Phase | Tasks | Was |
|---|---|---|
| A | 1-4 | Bugfixes (Decay, git add -A, numpy overflow, cycle overlap) |
| B | 5-6 | Trace Collection + Evaluator in Way2AGI pipeline/ |
| C | 7-8 | Training Trigger + Sidekick Trace Logging |
| D | 9-11 | 3 Benchmark-Durchlaeufe mit Vergleich |

Geschaetzte Code-Aenderungen: ~400 Zeilen neu, ~20 Zeilen gefixt.
