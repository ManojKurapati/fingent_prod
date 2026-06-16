"""traced_agent_run: one span + one audit event, with token/cost/latency captured."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    ModelTier,
    OrchestrationMode,
    RawCompletion,
    Step,
    StepContext,
    StepGraph,
    parallel,
)
from app.audit import InMemoryAuditLog
from app.observability import Tracer, traced_agent_run


async def _transport(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=10, output_tokens=4)


class _DummyOrchestrator(BaseOrchestrator[int]):
    group = "dummy"
    mode = OrchestrationMode.PARALLEL

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    def build_graph(self, request: int) -> StepGraph:
        async def _work(ctx: StepContext) -> int:
            await self._gateway.complete(prompt="do work", tier=ModelTier.HAIKU)
            return request * 2

        return parallel([Step(name="work", run=_work)])


def _clock() -> Callable[[], float]:
    ticks = iter([100.0, 102.5])
    return lambda: next(ticks)


async def test_traced_run_emits_one_span_with_token_cost_latency() -> None:
    gateway = ClaudeGateway(transport=_transport)
    audit = InMemoryAuditLog()
    tracer = Tracer(clock=_clock())
    orch = _DummyOrchestrator(gateway)

    record = await traced_agent_run(
        orch, 21, tracer=tracer, audit=audit, gateway=gateway, correlation_id="c1"
    )

    assert record.result.outputs["work"] == 42
    assert len(tracer.spans) == 1
    span = tracer.spans[0]
    assert span.name == "agent.run:dummy"
    assert span.attributes["calls"] == 1
    assert span.attributes["input_tokens"] == 10
    assert span.attributes["output_tokens"] == 4
    assert span.attributes["cost_usd"] == pytest.approx((10 * 1.0 + 4 * 5.0) / 1_000_000)
    assert span.duration == pytest.approx(2.5)


async def test_traced_run_records_one_audit_event() -> None:
    gateway = ClaudeGateway(transport=_transport)
    audit = InMemoryAuditLog()
    tracer = Tracer(clock=_clock())

    await traced_agent_run(
        _DummyOrchestrator(gateway),
        5,
        tracer=tracer,
        audit=audit,
        gateway=gateway,
        correlation_id="c2",
    )

    events = await audit.events(correlation_id="c2")
    run_events = [e for e in events if e.action == "agent.run"]
    assert len(run_events) == 1
    payload = run_events[0].payload
    assert payload["group"] == "dummy"
    assert payload["steps"] == ["work"]
    assert payload["calls"] == 1
    assert payload["duration_s"] == pytest.approx(2.5)


async def test_per_run_token_delta_is_isolated_across_runs() -> None:
    """A second run's span reflects only its own usage, not the cumulative total."""
    gateway = ClaudeGateway(transport=_transport)
    audit = InMemoryAuditLog()
    tracer = Tracer()
    orch = _DummyOrchestrator(gateway)

    await traced_agent_run(orch, 1, tracer=tracer, audit=audit, gateway=gateway)
    await traced_agent_run(orch, 2, tracer=tracer, audit=audit, gateway=gateway)

    assert tracer.spans[0].attributes["input_tokens"] == 10
    assert tracer.spans[1].attributes["input_tokens"] == 10  # delta, not 20
    assert gateway.usage.input_tokens == 20  # cumulative on the gateway
