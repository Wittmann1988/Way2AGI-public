"""
Cloud LLM Provider Integration for Way2AGI Orchestrator.

Manages Claude, GPT-4, Gemini, and Groq as fallback endpoints
with unified call interface, cost tracking, and smart routing.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK imports — each may be absent
# ---------------------------------------------------------------------------

try:
    import anthropic  # type: ignore
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

try:
    import openai  # type: ignore
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    import google.generativeai as genai  # type: ignore
    _HAS_GOOGLE = True
except ImportError:
    _HAS_GOOGLE = False

try:
    import groq as groq_sdk  # type: ignore
    _HAS_GROQ = True
except ImportError:
    _HAS_GROQ = False

# ---------------------------------------------------------------------------
# Cost table (approximate USD per 1M input tokens)
# ---------------------------------------------------------------------------

COST_PER_M_INPUT = {
    "claude": 3.0,
    "gpt4": 2.5,
    "gemini": 0.0,
    "groq": 0.0,
}

COST_PER_M_OUTPUT = {
    "claude": 15.0,
    "gpt4": 10.0,
    "gemini": 0.0,
    "groq": 0.0,
}

# ---------------------------------------------------------------------------
# Provider priority by task type
# ---------------------------------------------------------------------------

TASK_PRIORITY = {
    "coding": ["gpt4", "claude", "groq", "gemini"],
    "reasoning": ["claude", "gpt4", "groq", "gemini"],
    "quick": ["groq", "gemini", "gpt4", "claude"],
    "default": ["groq", "gemini", "gpt4", "claude"],  # cheapest first
}

# Minimum seconds between calls to the same provider (simple rate limit)
RATE_LIMIT_SECONDS = {
    "claude": 0.5,
    "gpt4": 0.3,
    "gemini": 0.2,
    "groq": 0.1,
}

MAX_RETRIES = 2


@dataclass
class CallRecord:
    """Single API call record for logging / cost tracking."""
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    duration_s: float
    success: bool
    error: Optional[str] = None


@dataclass
class CloudProviderManager:
    """Manages cloud LLM providers with unified interface and cost tracking."""

    _clients: dict = field(default_factory=dict, init=False, repr=False)
    _last_call_ts: dict = field(default_factory=dict, init=False, repr=False)
    _history: list = field(default_factory=list, init=False, repr=False)
    _total_cost: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._init_providers()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_providers(self) -> None:
        """Try to initialise each provider from environment variables."""

        # --- Anthropic / Claude ---
        if _HAS_ANTHROPIC:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if key:
                try:
                    client = anthropic.Anthropic(api_key=key)
                    self._clients["claude"] = client
                    logger.info("Claude provider initialised.")
                except Exception as exc:
                    logger.warning("Claude init failed: %s", exc)

        # --- OpenAI / GPT-4 ---
        if _HAS_OPENAI:
            key = os.environ.get("OPENAI_API_KEY")
            if key:
                try:
                    client = openai.OpenAI(api_key=key)
                    self._clients["gpt4"] = client
                    logger.info("GPT-4 provider initialised.")
                except Exception as exc:
                    logger.warning("GPT-4 init failed: %s", exc)

        # --- Google / Gemini ---
        if _HAS_GOOGLE:
            key = os.environ.get("GOOGLE_API_KEY")
            if key:
                try:
                    genai.configure(api_key=key)
                    self._clients["gemini"] = genai
                    logger.info("Gemini provider initialised.")
                except Exception as exc:
                    logger.warning("Gemini init failed: %s", exc)

        # --- Groq ---
        if _HAS_GROQ:
            key = os.environ.get("GROQ_API_KEY")
            if key:
                try:
                    client = groq_sdk.Groq(api_key=key)
                    self._clients["groq"] = client
                    logger.info("Groq provider initialised.")
                except Exception as exc:
                    logger.warning("Groq init failed: %s", exc)

        logger.info(
            "CloudProviderManager ready — %d provider(s): %s",
            len(self._clients),
            ", ".join(self._clients.keys()) or "(none)",
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def list_available(self) -> list[str]:
        """Return names of providers that are configured and ready."""
        return list(self._clients.keys())

    @property
    def total_cost(self) -> float:
        """Approximate total USD spent this session."""
        return self._total_cost

    @property
    def history(self) -> list[CallRecord]:
        """Full call history."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self, provider: str) -> None:
        """Sleep if needed to respect per-provider rate limit."""
        min_gap = RATE_LIMIT_SECONDS.get(provider, 0.5)
        last = self._last_call_ts.get(provider, 0.0)
        elapsed = time.time() - last
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)

    def _mark_called(self, provider: str) -> None:
        self._last_call_ts[provider] = time.time()

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_cost(
        provider: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        input_cost = (prompt_tokens / 1_000_000) * COST_PER_M_INPUT.get(provider, 0)
        output_cost = (completion_tokens / 1_000_000) * COST_PER_M_OUTPUT.get(provider, 0)
        return input_cost + output_cost

    # ------------------------------------------------------------------
    # Individual provider calls
    # ------------------------------------------------------------------

    def _call_claude(
        self, prompt: str, system: Optional[str], max_tokens: int
    ) -> tuple[str, int, int]:
        client = self._clients["claude"]
        kwargs: dict = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        text = resp.content[0].text
        p_tok = resp.usage.input_tokens
        c_tok = resp.usage.output_tokens
        return text, p_tok, c_tok

    def _call_gpt4(
        self, prompt: str, system: Optional[str], max_tokens: int
    ) -> tuple[str, int, int]:
        client = self._clients["gpt4"]
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        p_tok = resp.usage.prompt_tokens if resp.usage else 0
        c_tok = resp.usage.completion_tokens if resp.usage else 0
        return text, p_tok, c_tok

    def _call_gemini(
        self, prompt: str, system: Optional[str], max_tokens: int
    ) -> tuple[str, int, int]:
        sdk = self._clients["gemini"]
        model = sdk.GenerativeModel(
            "gemini-2.0-flash",
            system_instruction=system if system else None,
        )
        resp = model.generate_content(
            prompt,
            generation_config=sdk.types.GenerationConfig(max_output_tokens=max_tokens),
        )
        text = resp.text
        # Gemini usage metadata may not always be present
        p_tok = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
        c_tok = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0
        return text, p_tok, c_tok

    def _call_groq(
        self, prompt: str, system: Optional[str], max_tokens: int
    ) -> tuple[str, int, int]:
        client = self._clients["groq"]
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        p_tok = resp.usage.prompt_tokens if resp.usage else 0
        c_tok = resp.usage.completion_tokens if resp.usage else 0
        return text, p_tok, c_tok

    _DISPATCH = {
        "claude": _call_claude,
        "gpt4": _call_gpt4,
        "gemini": _call_gemini,
        "groq": _call_groq,
    }

    # ------------------------------------------------------------------
    # Unified call interface
    # ------------------------------------------------------------------

    def call(
        self,
        provider: str,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        """
        Call a specific cloud provider.

        Args:
            provider: One of 'claude', 'gpt4', 'gemini', 'groq'.
            prompt: The user prompt.
            system: Optional system message.
            max_tokens: Max output tokens.

        Returns:
            The model's text response.

        Raises:
            ValueError: If provider is unknown or not available.
            RuntimeError: If all retries are exhausted.
        """
        if provider not in self._DISPATCH:
            raise ValueError(f"Unknown provider: {provider}")
        if provider not in self._clients:
            raise ValueError(
                f"Provider '{provider}' is not available. "
                f"Available: {self.list_available()}"
            )

        dispatch_fn = self._DISPATCH[provider]
        last_err: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            self._wait_for_rate_limit(provider)
            t0 = time.time()
            try:
                text, p_tok, c_tok = dispatch_fn(self, prompt, system, max_tokens)
                duration = time.time() - t0
                self._mark_called(provider)

                cost = self._estimate_cost(provider, p_tok, c_tok)
                self._total_cost += cost

                record = CallRecord(
                    provider=provider,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    cost_usd=cost,
                    duration_s=round(duration, 3),
                    success=True,
                )
                self._history.append(record)

                logger.info(
                    "[%s] %d+%d tok | $%.6f | %.2fs",
                    provider, p_tok, c_tok, cost, duration,
                )
                return text

            except Exception as exc:
                duration = time.time() - t0
                last_err = exc
                record = CallRecord(
                    provider=provider,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=0.0,
                    duration_s=round(duration, 3),
                    success=False,
                    error=str(exc),
                )
                self._history.append(record)
                logger.warning(
                    "[%s] attempt %d/%d failed: %s",
                    provider, attempt, MAX_RETRIES, exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(1.0 * attempt)  # simple backoff

        raise RuntimeError(
            f"Provider '{provider}' failed after {MAX_RETRIES} retries: {last_err}"
        )

    # ------------------------------------------------------------------
    # Smart routing
    # ------------------------------------------------------------------

    def call_best(
        self,
        prompt: str,
        system: Optional[str] = None,
        task_type: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        """
        Pick the best available provider for the task and call it.

        Args:
            prompt: The user prompt.
            system: Optional system message.
            task_type: One of 'coding', 'reasoning', 'quick', or None (default).
            max_tokens: Max output tokens.

        Returns:
            The model's text response.

        Raises:
            RuntimeError: If no provider is available or all fail.
        """
        available = set(self.list_available())
        if not available:
            raise RuntimeError(
                "No cloud providers configured. "
                "Set at least one API key env var "
                "(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY)."
            )

        priority = TASK_PRIORITY.get(task_type or "default", TASK_PRIORITY["default"])
        candidates = [p for p in priority if p in available]

        if not candidates:
            raise RuntimeError(
                f"No provider available for task_type='{task_type}'. "
                f"Available: {self.list_available()}"
            )

        last_err: Optional[Exception] = None
        for provider in candidates:
            try:
                return self.call(provider, prompt, system=system, max_tokens=max_tokens)
            except Exception as exc:
                logger.warning(
                    "call_best: %s failed, trying next. Error: %s", provider, exc
                )
                last_err = exc

        raise RuntimeError(
            f"All providers failed for task_type='{task_type}': {last_err}"
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a summary of session usage."""
        calls_by_provider: dict[str, int] = {}
        cost_by_provider: dict[str, float] = {}
        for rec in self._history:
            if rec.success:
                calls_by_provider[rec.provider] = (
                    calls_by_provider.get(rec.provider, 0) + 1
                )
                cost_by_provider[rec.provider] = (
                    cost_by_provider.get(rec.provider, 0.0) + rec.cost_usd
                )
        return {
            "available_providers": self.list_available(),
            "total_calls": len(self._history),
            "successful_calls": sum(1 for r in self._history if r.success),
            "failed_calls": sum(1 for r in self._history if not r.success),
            "total_cost_usd": round(self._total_cost, 6),
            "calls_by_provider": calls_by_provider,
            "cost_by_provider": {
                k: round(v, 6) for k, v in cost_by_provider.items()
            },
        }
