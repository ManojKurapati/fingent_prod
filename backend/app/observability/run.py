"""Run an orchestrator with tracing + audit.

:func:`traced_agent_run` wraps any :class:`BaseOrchestrator` run so that every
agent run emits exactly one trace span (with token/cost/latency attributes) and
one ``agent.run`` audit event. This is the single instrumented entry point the
cross-agent chain and the API workers use, so observability is uniform and not
something each agent must remember to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.core import BaseOrchestrator, ClaudeGateway, EmitFn, RunResult
from app.agents.core.gateway import TokenUsage
from app.audit import AuditEvent, InMemoryAuditLog
from app.observability.tracing import Tracer, TraceSpan


@dataclass(frozen=True, slots=True)
class _UsageSnapshot:
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _snapshot(usage: TokenUsage) -> _UsageSnapshot:
    return _UsageSnapshot(
        calls=usage.calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )


def agent_run_attributes(before: TokenUsage, after: TokenUsage) -> dict[str, Any]:
    """The token/cost delta consumed by a single agent run."""
    b, a = _snapshot(before), _snapshot(after)
    return {
        "calls": a.calls - b.calls,
        "input_tokens": a.input_tokens - b.input_tokens,
        "output_tokens": a.output_tokens - b.output_tokens,
        "cost_usd": round(a.cost_usd - b.cost_usd, 10),
    }


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    """The observability artefacts produced by one traced agent run."""

    group: str
    result: RunResult
    span: TraceSpan
    audit_event: AuditEvent


async def traced_agent_run(
    orchestrator: BaseOrchestrator[Any],
    request: Any,
    *,
    tracer: Tracer,
    audit: InMemoryAuditLog,
    gateway: ClaudeGateway,
    emit: EmitFn | None = None,
    correlation_id: str | None = None,
    actor: str | None = None,
) -> AgentRunRecord:
    """Run ``orchestrator`` for ``request``, emitting one trace span + audit event.

    Token/cost are measured as the delta of the shared gateway's accounting across
    the run, so per-agent cost is attributable even though the gateway is shared.
    """
    group = orchestrator.group
    before = _copy_usage(gateway.usage)

    async with tracer.span(f"agent.run:{group}", group=group) as span:
        result = await orchestrator.run(request, emit=emit)
        attrs = agent_run_attributes(before, gateway.usage)
        for key, value in attrs.items():
            span.set(key, value)
        span.set("steps", list(result.order))

    recorded = tracer.spans[-1]
    event = await audit.record(
        actor=actor or group,
        action="agent.run",
        payload={
            "group": group,
            "steps": list(result.order),
            "duration_s": recorded.duration,
            **attrs,
        },
        correlation_id=correlation_id,
    )
    return AgentRunRecord(group=group, result=result, span=recorded, audit_event=event)


def _copy_usage(usage: TokenUsage) -> TokenUsage:
    """A frozen-in-time copy so the before-snapshot is not mutated by later calls."""
    return TokenUsage(
        calls=usage.calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )
