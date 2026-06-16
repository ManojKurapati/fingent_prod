"""Tests for the Claude API gateway: model routing, retries, token accounting."""

import pytest
from app.agents.core import (
    ClaudeGateway,
    GatewayError,
    LLMResponse,
    ModelTier,
    RawCompletion,
)


def _transport_returning(text: str, *, in_tokens: int = 10, out_tokens: int = 5):
    calls: list[dict[str, object]] = []

    async def _transport(model: str, prompt: str, **kw: object) -> RawCompletion:
        calls.append({"model": model, "prompt": prompt, **kw})
        return RawCompletion(text=text, input_tokens=in_tokens, output_tokens=out_tokens)

    _transport.calls = calls  # type: ignore[attr-defined]
    return _transport


async def test_routes_opus_and_haiku_to_distinct_models() -> None:
    transport = _transport_returning("ok")
    gw = ClaudeGateway(transport=transport)

    await gw.complete(prompt="hi", tier=ModelTier.OPUS)
    await gw.complete(prompt="hi", tier=ModelTier.HAIKU)

    models = [c["model"] for c in transport.calls]  # type: ignore[attr-defined]
    assert "opus" in models[0]
    assert "haiku" in models[1]
    assert models[0] != models[1]


async def test_returns_typed_response_with_usage() -> None:
    gw = ClaudeGateway(transport=_transport_returning("answer", in_tokens=12, out_tokens=8))
    resp = await gw.complete(prompt="q", tier=ModelTier.HAIKU)

    assert isinstance(resp, LLMResponse)
    assert resp.text == "answer"
    assert resp.input_tokens == 12
    assert resp.output_tokens == 8
    assert resp.tier is ModelTier.HAIKU


async def test_token_accounting_accumulates_across_calls() -> None:
    gw = ClaudeGateway(transport=_transport_returning("x", in_tokens=10, out_tokens=4))
    await gw.complete(prompt="a", tier=ModelTier.HAIKU)
    await gw.complete(prompt="b", tier=ModelTier.OPUS)

    usage = gw.usage
    assert usage.calls == 2
    assert usage.input_tokens == 20
    assert usage.output_tokens == 8
    # cost is tracked and strictly positive once tokens are spent
    assert usage.cost_usd > 0
    # per-tier breakdown is available
    assert usage.by_tier[ModelTier.OPUS].calls == 1
    assert usage.by_tier[ModelTier.HAIKU].calls == 1


async def test_retries_on_transient_error_then_succeeds() -> None:
    attempts = {"n": 0}

    async def flaky(model: str, prompt: str, **kw: object) -> RawCompletion:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("transient")
        return RawCompletion(text="recovered", input_tokens=1, output_tokens=1)

    gw = ClaudeGateway(transport=flaky, max_retries=3, sleep=_no_sleep)
    resp = await gw.complete(prompt="q", tier=ModelTier.HAIKU)

    assert resp.text == "recovered"
    assert attempts["n"] == 3


async def test_gives_up_after_max_retries_and_raises_gateway_error() -> None:
    async def always_fail(model: str, prompt: str, **kw: object) -> RawCompletion:
        raise ConnectionError("down")

    gw = ClaudeGateway(transport=always_fail, max_retries=2, sleep=_no_sleep)
    with pytest.raises(GatewayError):
        await gw.complete(prompt="q", tier=ModelTier.OPUS)


async def test_does_not_retry_unexpected_error() -> None:
    attempts = {"n": 0}

    async def bad(model: str, prompt: str, **kw: object) -> RawCompletion:
        attempts["n"] += 1
        raise ValueError("non-retryable")

    gw = ClaudeGateway(transport=bad, max_retries=5, sleep=_no_sleep)
    with pytest.raises(ValueError):
        await gw.complete(prompt="q", tier=ModelTier.HAIKU)
    assert attempts["n"] == 1


async def _no_sleep(_seconds: float) -> None:
    return None
