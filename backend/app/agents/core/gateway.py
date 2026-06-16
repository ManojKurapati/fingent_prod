"""Claude API gateway — FROZEN CONTRACT.

Single egress for model calls: model routing (Opus for reasoning/orchestration,
Haiku for cheap high-volume subagent tasks), retries with backoff, and token/cost
accounting. Agents never call a model SDK directly — they call this gateway.

The network transport is injected so the gateway is fully testable without a real
API key. A production transport wrapping the Anthropic SDK is provided separately.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum


class ModelTier(StrEnum):
    """Which Claude model class to route a request to."""

    OPUS = "opus"
    HAIKU = "haiku"


# Concrete model ids per tier. Opus 4.8 for reasoning/orchestration; Haiku 4.5
# for cheap, high-volume subagent tasks.
MODEL_IDS: dict[ModelTier, str] = {
    ModelTier.OPUS: "claude-opus-4-8",
    ModelTier.HAIKU: "claude-haiku-4-5-20251001",
}

# USD per 1M tokens (input, output). Configurable; defaults are order-of-magnitude
# placeholders used only for relative cost accounting, not billing.
DEFAULT_PRICING: dict[ModelTier, tuple[float, float]] = {
    ModelTier.OPUS: (15.0, 75.0),
    ModelTier.HAIKU: (1.0, 5.0),
}


@dataclass(frozen=True, slots=True)
class RawCompletion:
    """What an injected transport returns for one model call."""

    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A completed model call, normalised for callers."""

    text: str
    tier: ModelTier
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class TierUsage:
    """Accumulated usage for a single tier."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class TokenUsage:
    """Total token/cost accounting across all calls made through the gateway."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_tier: dict[ModelTier, TierUsage] = field(default_factory=dict)


class GatewayError(RuntimeError):
    """Raised when a model call exhausts its retries on transient errors."""


# A transport: (model_id, prompt, **kwargs) -> RawCompletion.
Transport = Callable[..., Awaitable[RawCompletion]]
SleepFn = Callable[[float], Awaitable[None]]

# Errors we treat as transient and retry.
_RETRYABLE: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)


async def _default_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


class ClaudeGateway:
    """Routes, retries, and meters all Claude model calls."""

    def __init__(
        self,
        transport: Transport,
        *,
        max_retries: int = 3,
        base_delay: float = 0.05,
        sleep: SleepFn | None = None,
        pricing: dict[ModelTier, tuple[float, float]] | None = None,
    ) -> None:
        self._transport = transport
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._sleep = sleep or _default_sleep
        self._pricing = pricing or DEFAULT_PRICING
        self._usage = TokenUsage(by_tier={tier: TierUsage() for tier in ModelTier})

    @property
    def usage(self) -> TokenUsage:
        """A snapshot of accumulated token/cost accounting."""
        return self._usage

    async def complete(
        self,
        *,
        prompt: str,
        tier: ModelTier = ModelTier.HAIKU,
        **kwargs: object,
    ) -> LLMResponse:
        """Run one completion, routing by ``tier`` with retries and accounting."""
        model = MODEL_IDS[tier]
        raw = await self._call_with_retries(model, prompt, **kwargs)
        self._record(tier, raw)
        return LLMResponse(
            text=raw.text,
            tier=tier,
            model=model,
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
        )

    async def _call_with_retries(self, model: str, prompt: str, **kwargs: object) -> RawCompletion:
        last_exc: BaseException | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._transport(model, prompt, **kwargs)
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    await self._sleep(self._base_delay * (2**attempt))
        raise GatewayError(
            f"model call to {model} failed after {self._max_retries} attempts"
        ) from last_exc

    def _record(self, tier: ModelTier, raw: RawCompletion) -> None:
        in_rate, out_rate = self._pricing[tier]
        cost = (raw.input_tokens * in_rate + raw.output_tokens * out_rate) / 1_000_000
        self._usage.calls += 1
        self._usage.input_tokens += raw.input_tokens
        self._usage.output_tokens += raw.output_tokens
        self._usage.cost_usd += cost
        t = self._usage.by_tier[tier]
        t.calls += 1
        t.input_tokens += raw.input_tokens
        t.output_tokens += raw.output_tokens
        t.cost_usd += cost
