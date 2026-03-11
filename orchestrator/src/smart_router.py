"""
Smart Router — Intelligent task-based model routing for Way2AGI.

Replaces dumb round-robin / try-in-order with actual intelligence:
1. Classify the task (coding, reasoning, security, etc.)
2. Check which nodes are alive and how loaded they are
3. Pick the optimal (model, endpoint, node) based on task + availability
4. If preferred node is down, fall back immediately — no waiting
5. If Desktop is sleeping, send WoL and use another node while it wakes

Usage:
    router = SmartRouter()
    result = router.route("Write a Python parser for MIFARE dumps")
    # => {"model": "nemotron-3-nano:30b", "endpoint": "http://YOUR_CONTROLLER_IP:8080",
    #     "node": "jetson", "strategy": "local_inference"}
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    CODING = "coding"
    REASONING = "reasoning"
    ANALYSIS = "analysis"
    QUICK_CHECK = "quick_check"
    TRAINING = "training"
    SECURITY = "security"
    GERMAN = "german"
    SELF_REFLECTION = "self_reflection"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------

class NodeState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    SLEEPING = "sleeping"      # Desktop — reachable via WoL
    WOL_SENT = "wol_sent"     # WoL packet sent, waiting for wake
    DEGRADED = "degraded"     # Responding but slow / partial


@dataclass
class Endpoint:
    """A single inference endpoint on a node."""
    url: str                          # e.g. "http://YOUR_CONTROLLER_IP:8080"
    engine: str                       # "llama.cpp" | "ollama"
    health_path: str = "/health"      # Path to check liveness
    models: list[str] = field(default_factory=list)


@dataclass
class NodeConfig:
    """Static configuration for a compute node."""
    name: str
    ip: str
    mac: Optional[str] = None         # For WoL
    endpoints: list[Endpoint] = field(default_factory=list)
    capabilities: list[TaskType] = field(default_factory=list)
    weight: int = 50                  # Base priority (higher = preferred)
    is_gpu: bool = False
    can_sleep: bool = False           # Supports WoL wake


@dataclass
class NodeStatus:
    """Runtime status for a node, updated by health checks."""
    state: NodeState = NodeState.OFFLINE
    active_requests: int = 0
    last_check: float = 0.0
    last_latency_ms: float = 0.0
    wol_sent_at: float = 0.0
    consecutive_failures: int = 0


# ---------------------------------------------------------------------------
# Node catalog — all Way2AGI compute nodes
# ---------------------------------------------------------------------------

NODES: dict[str, NodeConfig] = {
    "jetson": NodeConfig(
        name="jetson",
        ip="YOUR_CONTROLLER_IP",
        endpoints=[
            Endpoint(
                url="http://YOUR_CONTROLLER_IP:8080",
                engine="llama.cpp",
                health_path="/health",
                models=["nemotron-3-nano:30b", "lfm2:24b"],
            ),
            Endpoint(
                url="http://YOUR_CONTROLLER_IP:11434",
                engine="ollama",
                health_path="/api/tags",
                models=["nemotron-3-nano:30b", "lfm2:24b", "smallthinker:1.8b"],
            ),
        ],
        capabilities=[
            TaskType.REASONING, TaskType.ANALYSIS, TaskType.CODING,
            TaskType.SECURITY, TaskType.GERMAN, TaskType.SELF_REFLECTION,
        ],
        weight=80,
        is_gpu=True,
    ),
    "desktop": NodeConfig(
        name="desktop",
        ip="YOUR_DESKTOP_IP",
        mac="XX:XX:XX:XX:XX:XX",  # TODO: fill in real MAC
        endpoints=[
            Endpoint(
                url="http://YOUR_DESKTOP_IP:8080",
                engine="llama.cpp",
                health_path="/health",
                models=["lfm2:24b", "step-3.5-flash", "qwen3.5:9b"],
            ),
            Endpoint(
                url="http://YOUR_DESKTOP_IP:11434",
                engine="ollama",
                health_path="/api/tags",
                models=["lfm2:24b", "step-3.5-flash", "qwen3.5:9b"],
            ),
        ],
        capabilities=[
            TaskType.CODING, TaskType.REASONING, TaskType.ANALYSIS,
            TaskType.TRAINING, TaskType.SECURITY, TaskType.GERMAN,
        ],
        weight=90,
        is_gpu=True,
        can_sleep=True,
    ),
    "zenbook": NodeConfig(
        name="zenbook",
        ip="YOUR_LAPTOP_IP",
        endpoints=[
            Endpoint(
                url="http://YOUR_LAPTOP_IP:11434",
                engine="ollama",
                health_path="/api/tags",
                models=["lfm2:24b", "smallthinker:1.8b", "qwen3:1.7b"],
            ),
            Endpoint(
                url="http://YOUR_LAPTOP_IP:8080",
                engine="llama.cpp",
                health_path="/health",
                models=["smallthinker:1.8b"],
            ),
        ],
        capabilities=[
            TaskType.QUICK_CHECK, TaskType.GERMAN,
        ],
        weight=30,
    ),
    "s24": NodeConfig(
        name="s24",
        ip="YOUR_MOBILE_IP",
        endpoints=[
            Endpoint(
                url="http://YOUR_MOBILE_IP:11434",
                engine="ollama",
                health_path="/api/tags",
                models=["qwen3:1.7b"],
            ),
        ],
        capabilities=[
            TaskType.QUICK_CHECK,
        ],
        weight=20,
    ),
}


# Cloud providers (always available, higher latency, costs money)
CLOUD_ENDPOINTS: list[dict[str, str]] = [
    {"name": "claude", "provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    {"name": "gpt4", "provider": "openai", "model": "gpt-4o"},
    {"name": "groq", "provider": "groq", "model": "llama-3.3-70b-versatile"},
]


# ---------------------------------------------------------------------------
# Keyword maps for task classification
# ---------------------------------------------------------------------------

_TASK_KEYWORDS: dict[TaskType, list[str]] = {
    TaskType.CODING: [
        "code", "coding", "program", "python", "javascript", "typescript",
        "rust", "function", "class", "bug", "debug", "refactor", "implement",
        "api", "endpoint", "parser", "compiler", "script", "module",
        "git", "commit", "merge", "test", "unittest", "pytest",
    ],
    TaskType.REASONING: [
        "reason", "reasoning", "think", "logic", "proof", "math",
        "calculate", "solve", "theorem", "infer", "deduce", "plan",
        "strategy", "decision", "evaluate", "compare", "tradeoff",
    ],
    TaskType.ANALYSIS: [
        "analy", "research", "paper", "arxiv", "study", "survey",
        "review", "summarize", "summary", "extract", "insight",
        "dataset", "benchmark", "metric", "evaluate", "report",
    ],
    TaskType.QUICK_CHECK: [
        "check", "verify", "validate", "quick", "simple", "short",
        "yes or no", "true or false", "confirm", "lookup", "fact",
        "translate", "format", "convert",
    ],
    TaskType.TRAINING: [
        "train", "training", "fine-tune", "finetune", "sft", "dpo",
        "lora", "qlora", "gguf", "quantize", "distill", "abliterate",
        "pipeline", "epoch", "batch", "checkpoint",
    ],
    TaskType.SECURITY: [
        "security", "hack", "exploit", "vuln", "pentest", "penetration",
        "nmap", "proxmark", "rfid", "nfc", "mifare", "dump", "crack",
        "bettercap", "wifi", "deauth", "brute", "payload", "reverse",
        "shell", "privilege", "escalation", "cve",
    ],
    TaskType.GERMAN: [
        "deutsch", "german", "uebersetze", "uebersetzung", "erklaere",
        "zusammenfassung", "bitte", "danke", "schreibe", "erstelle",
    ],
    TaskType.SELF_REFLECTION: [
        "reflect", "self-mirror", "identity", "who am i", "bewusstsein",
        "consciousness", "introspect", "self-model", "meta-cognition",
        "self-improve", "memory recall", "elias",
    ],
}

# Pre-compile patterns for faster matching
_TASK_PATTERNS: dict[TaskType, re.Pattern] = {
    task_type: re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")",
        re.IGNORECASE,
    )
    for task_type, keywords in _TASK_KEYWORDS.items()
}


# ---------------------------------------------------------------------------
# Routing preferences per task type
# ---------------------------------------------------------------------------

# Ordered list of (node_name, preferred_model) tuples.  First match wins.
_ROUTING_PREFS: dict[TaskType, list[tuple[str, Optional[str]]]] = {
    TaskType.CODING: [
        ("desktop", "lfm2:24b"),
        ("jetson", "nemotron-3-nano:30b"),
        # cloud fallback handled separately
    ],
    TaskType.REASONING: [
        ("jetson", "nemotron-3-nano:30b"),
        ("desktop", "lfm2:24b"),
    ],
    TaskType.ANALYSIS: [
        ("jetson", "nemotron-3-nano:30b"),
        ("desktop", "lfm2:24b"),
    ],
    TaskType.QUICK_CHECK: [
        ("zenbook", "smallthinker:1.8b"),
        ("s24", "qwen3:1.7b"),
        ("jetson", "smallthinker:1.8b"),
    ],
    TaskType.TRAINING: [
        ("desktop", None),  # Training ONLY on Desktop
    ],
    TaskType.SECURITY: [
        ("jetson", "nemotron-3-nano:30b"),  # Abliterated models
    ],
    TaskType.GERMAN: [
        ("jetson", "nemotron-3-nano:30b"),
        ("desktop", "lfm2:24b"),
        ("zenbook", "lfm2:24b"),
    ],
    TaskType.SELF_REFLECTION: [
        ("jetson", "nemotron-3-nano:30b"),
        ("desktop", "lfm2:24b"),
    ],
    TaskType.UNKNOWN: [
        ("jetson", "nemotron-3-nano:30b"),
        ("desktop", "lfm2:24b"),
        ("zenbook", "smallthinker:1.8b"),
    ],
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _http_check(url: str, timeout: float = 2.0) -> tuple[bool, float]:
    """
    Perform a quick HTTP GET and return (is_alive, latency_ms).
    Uses only stdlib urllib — no requests/httpx needed.
    """
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(512)  # Read small chunk to confirm response
            latency = (time.monotonic() - start) * 1000
            return resp.status < 500, latency
    except (urllib.error.URLError, OSError, TimeoutError):
        latency = (time.monotonic() - start) * 1000
        return False, latency


def _send_wol(mac: str) -> bool:
    """
    Send a Wake-on-LAN magic packet via wakeonlan or etherwake.
    Returns True if the command executed without error.
    """
    if not mac or mac.startswith("XX"):
        logger.warning("WoL skipped — no valid MAC configured for Desktop")
        return False

    for cmd in ["wakeonlan", "etherwake"]:
        try:
            result = subprocess.run(
                [cmd, mac],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("WoL packet sent via %s to %s", cmd, mac)
                return True
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            logger.warning("WoL command %s timed out", cmd)
            continue

    logger.error("WoL failed — neither wakeonlan nor etherwake available")
    return False


# ---------------------------------------------------------------------------
# SmartRouter
# ---------------------------------------------------------------------------

class SmartRouter:
    """
    Intelligent task-aware model router.

    Maintains live node status, classifies incoming tasks, and routes
    to the optimal (model, endpoint, node) combination.
    """

    # How long before a health check result is considered stale
    HEALTH_TTL_S: float = 15.0
    # How long to wait after WoL before rechecking Desktop
    WOL_GRACE_S: float = 30.0
    # Max active requests before a node is considered "loaded"
    LOAD_THRESHOLD: int = 4

    def __init__(self, network_manager: Any = None) -> None:
        self._nodes = dict(NODES)
        self._status: dict[str, NodeStatus] = {
            name: NodeStatus() for name in self._nodes
        }
        self._network_manager = network_manager
        self._lock = threading.Lock()

        logger.info(
            "SmartRouter initialized — %d local nodes, %d cloud endpoints",
            len(self._nodes),
            len(CLOUD_ENDPOINTS),
        )

    # ------------------------------------------------------------------
    # Node status management
    # ------------------------------------------------------------------

    @property
    def node_status(self) -> dict[str, NodeStatus]:
        """Read-only snapshot of current node status."""
        with self._lock:
            return dict(self._status)

    def update_status(self, node_name: str, state: NodeState) -> None:
        """Manually update a node's state (called by NetworkManager)."""
        with self._lock:
            if node_name in self._status:
                self._status[node_name].state = state
                self._status[node_name].last_check = time.monotonic()
                logger.debug("Node %s → %s (manual update)", node_name, state)

    def _check_node(self, name: str) -> NodeState:
        """
        Check if a node is reachable by probing its first endpoint.
        Updates internal status and returns the new state.
        """
        config = self._nodes.get(name)
        if not config or not config.endpoints:
            return NodeState.OFFLINE

        with self._lock:
            status = self._status[name]
            # Return cached result if still fresh
            elapsed = time.monotonic() - status.last_check
            if elapsed < self.HEALTH_TTL_S and status.state != NodeState.WOL_SENT:
                return status.state

        # Probe the first endpoint
        ep = config.endpoints[0]
        url = ep.url.rstrip("/") + ep.health_path
        alive, latency = _http_check(url)

        with self._lock:
            status = self._status[name]
            status.last_check = time.monotonic()
            status.last_latency_ms = latency

            if alive:
                status.state = NodeState.ONLINE
                status.consecutive_failures = 0
            else:
                status.consecutive_failures += 1
                if config.can_sleep and status.consecutive_failures <= 3:
                    status.state = NodeState.SLEEPING
                else:
                    status.state = NodeState.OFFLINE

            logger.debug(
                "Health check %s: %s (%.0fms)",
                name, status.state, latency,
            )
            return status.state

    def refresh_all(self) -> dict[str, NodeState]:
        """
        Probe all nodes in parallel and return their states.
        Useful at startup or when NetworkManager triggers a refresh.
        """
        threads: list[threading.Thread] = []
        results: dict[str, NodeState] = {}

        def _probe(n: str) -> None:
            results[n] = self._check_node(n)

        for node_name in self._nodes:
            t = threading.Thread(target=_probe, args=(node_name,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=5.0)

        logger.info(
            "Refresh complete: %s",
            ", ".join(f"{n}={s.value}" for n, s in results.items()),
        )
        return results

    def _increment_load(self, node_name: str) -> None:
        with self._lock:
            self._status[node_name].active_requests += 1

    def _decrement_load(self, node_name: str) -> None:
        with self._lock:
            st = self._status[node_name]
            st.active_requests = max(0, st.active_requests - 1)

    def release(self, node_name: str) -> None:
        """Call when a routed request completes to free the load slot."""
        self._decrement_load(node_name)

    # ------------------------------------------------------------------
    # Task classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_task(description: str) -> str:
        """
        Classify a task description into a TaskType using keyword matching.

        Returns the string value of the best-matching TaskType.
        If multiple types match, the one with the most keyword hits wins.
        Ties are broken by enum declaration order (first listed wins).
        """
        if not description or not description.strip():
            return TaskType.UNKNOWN.value

        scores: dict[TaskType, int] = {}
        text = description.lower()

        for task_type, pattern in _TASK_PATTERNS.items():
            hits = pattern.findall(text)
            if hits:
                scores[task_type] = len(hits)

        if not scores:
            return TaskType.UNKNOWN.value

        best = max(scores, key=lambda t: scores[t])
        logger.debug(
            "classify_task: %r → %s (scores: %s)",
            description[:60], best.value,
            {t.value: s for t, s in scores.items()},
        )
        return best.value

    # ------------------------------------------------------------------
    # Core routing
    # ------------------------------------------------------------------

    def route(self, task_description: str) -> dict[str, Any]:
        """
        Route a task to the optimal model and endpoint.

        Returns a dict:
            {
                "model": str,          # Model identifier
                "endpoint": str,       # Full URL to inference server
                "node": str,           # Node name (or "cloud")
                "strategy": str,       # "local_inference" | "cloud_api" | "wol_deferred"
                "task_type": str,      # Classified task type
                "fallback_chain": [],  # Remaining options if this fails
            }
        """
        task_type_str = self.classify_task(task_description)
        task_type = TaskType(task_type_str)

        prefs = _ROUTING_PREFS.get(task_type, _ROUTING_PREFS[TaskType.UNKNOWN])
        fallback_chain: list[dict[str, Any]] = []
        wol_triggered = False

        for node_name, preferred_model in prefs:
            config = self._nodes.get(node_name)
            if not config:
                continue

            state = self._check_node(node_name)

            # --- Node is online ---
            if state == NodeState.ONLINE:
                with self._lock:
                    load = self._status[node_name].active_requests
                if load >= self.LOAD_THRESHOLD:
                    logger.debug("Node %s overloaded (%d reqs), skipping", node_name, load)
                    continue

                endpoint, model = self._pick_endpoint_and_model(config, preferred_model)
                if endpoint is None:
                    continue

                self._increment_load(node_name)
                result = {
                    "model": model,
                    "endpoint": endpoint.url,
                    "node": node_name,
                    "strategy": "local_inference",
                    "task_type": task_type_str,
                    "fallback_chain": fallback_chain,
                }
                logger.info(
                    "Routed [%s] → %s/%s at %s",
                    task_type_str, node_name, model, endpoint.url,
                )
                return result

            # --- Desktop sleeping — send WoL, continue looking ---
            if state in (NodeState.SLEEPING, NodeState.OFFLINE) and config.can_sleep:
                if not wol_triggered:
                    self._trigger_wol(node_name, config)
                    wol_triggered = True
                # Add as deferred fallback
                endpoint, model = self._pick_endpoint_and_model(config, preferred_model)
                if endpoint:
                    fallback_chain.append({
                        "model": model,
                        "endpoint": endpoint.url,
                        "node": node_name,
                        "strategy": "wol_deferred",
                    })
                continue

            # --- Node offline, not wakeable — skip ---
            logger.debug("Node %s is %s, skipping", node_name, state.value)

        # --- No local node available — try cloud ---
        cloud = self._pick_cloud(task_type)
        if cloud:
            result = {
                "model": cloud["model"],
                "endpoint": f"{cloud['provider']}_api",
                "node": "cloud",
                "strategy": "cloud_api",
                "task_type": task_type_str,
                "fallback_chain": fallback_chain,
            }
            logger.info(
                "Routed [%s] → cloud/%s (%s)",
                task_type_str, cloud["model"], cloud["provider"],
            )
            return result

        # --- Nothing available (very bad) ---
        logger.error("No route available for task type %s", task_type_str)
        return {
            "model": None,
            "endpoint": None,
            "node": None,
            "strategy": "no_route",
            "task_type": task_type_str,
            "fallback_chain": fallback_chain,
            "error": "All nodes offline and no cloud API configured",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_endpoint_and_model(
        config: NodeConfig,
        preferred_model: Optional[str],
    ) -> tuple[Optional[Endpoint], Optional[str]]:
        """
        Select the best endpoint on a node for the preferred model.
        Returns (endpoint, model) or (None, None).
        """
        # Try to match preferred model first
        if preferred_model:
            for ep in config.endpoints:
                if preferred_model in ep.models:
                    return ep, preferred_model

        # Fall back to first endpoint with any model
        for ep in config.endpoints:
            if ep.models:
                return ep, ep.models[0]

        return None, None

    def _trigger_wol(self, node_name: str, config: NodeConfig) -> None:
        """Send WoL and update status to WOL_SENT."""
        if config.mac:
            sent = _send_wol(config.mac)
            if sent:
                with self._lock:
                    self._status[node_name].state = NodeState.WOL_SENT
                    self._status[node_name].wol_sent_at = time.monotonic()
                logger.info("WoL sent to %s — will recheck in %.0fs", node_name, self.WOL_GRACE_S)

    @staticmethod
    def _pick_cloud(task_type: TaskType) -> Optional[dict[str, str]]:
        """
        Select a cloud endpoint appropriate for the task.
        Training tasks NEVER go to cloud. Security prefers Groq (no filters).
        """
        if task_type == TaskType.TRAINING:
            return None  # Training requires local GPU

        if task_type == TaskType.SECURITY:
            # Groq with open models for security research
            for c in CLOUD_ENDPOINTS:
                if c["provider"] == "groq":
                    return c

        # Default: Claude for complex tasks, Groq for lighter ones
        if task_type in (TaskType.CODING, TaskType.REASONING, TaskType.ANALYSIS):
            for c in CLOUD_ENDPOINTS:
                if c["provider"] == "anthropic":
                    return c

        # Anything else — cheapest cloud option
        for c in CLOUD_ENDPOINTS:
            if c["provider"] == "groq":
                return c

        return CLOUD_ENDPOINTS[0] if CLOUD_ENDPOINTS else None

    # ------------------------------------------------------------------
    # Convenience: wait for WoL node and reroute
    # ------------------------------------------------------------------

    def wait_for_wol_and_reroute(
        self,
        task_description: str,
        timeout: float = 60.0,
    ) -> Optional[dict[str, Any]]:
        """
        Block until a WoL-sent node comes online, then reroute.
        Returns None if timeout expires.  Use in background threads only.
        """
        deadline = time.monotonic() + timeout

        wol_nodes = []
        with self._lock:
            for name, status in self._status.items():
                if status.state == NodeState.WOL_SENT:
                    wol_nodes.append(name)

        if not wol_nodes:
            return None

        logger.info("Waiting for WoL nodes %s (timeout %.0fs)", wol_nodes, timeout)

        while time.monotonic() < deadline:
            for name in wol_nodes:
                state = self._check_node(name)
                if state == NodeState.ONLINE:
                    logger.info("Node %s woke up — rerouting", name)
                    return self.route(task_description)
            time.sleep(5.0)

        logger.warning("WoL wait timed out after %.0fs", timeout)
        return None

    # ------------------------------------------------------------------
    # Debug / introspection
    # ------------------------------------------------------------------

    def status_summary(self) -> str:
        """Human-readable status of all nodes."""
        lines = ["SmartRouter Node Status:", "=" * 50]
        with self._lock:
            for name, config in self._nodes.items():
                st = self._status[name]
                models = []
                for ep in config.endpoints:
                    models.extend(ep.models)
                unique_models = sorted(set(models))
                lines.append(
                    f"  {name:10s} | {st.state.value:10s} | "
                    f"load={st.active_requests} | "
                    f"latency={st.last_latency_ms:.0f}ms | "
                    f"models={', '.join(unique_models)}"
                )
        lines.append("=" * 50)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions (for simple imports)
# ---------------------------------------------------------------------------

_default_router: Optional[SmartRouter] = None
_router_lock = threading.Lock()


def get_router() -> SmartRouter:
    """Get or create the singleton SmartRouter instance."""
    global _default_router
    with _router_lock:
        if _default_router is None:
            _default_router = SmartRouter()
        return _default_router


def classify_task(description: str) -> str:
    """Classify a task description. Module-level convenience function."""
    return SmartRouter.classify_task(description)


def route(task_description: str) -> dict[str, Any]:
    """Route a task. Module-level convenience function."""
    return get_router().route(task_description)
