"""Cross-agent orchestration.

A *chain* runs a sequence of group-agents where each link builds its request from
the accumulated outputs of the agents that ran before it. The whole chain shares
one ``correlation_id`` and every agent run is traced and audited (via
:func:`traced_agent_run`), so a multi-agent flow is observable end to end and its
consequential actions still land in the shared, default-deny approval queue.

This is the mechanism by which the Leadership/CFO agent invokes other enterprise
agents, and by which the financial-services chain
``research -> portfolio -> trading -> operations`` is composed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.agents.core import BaseOrchestrator, ClaudeGateway, EmitFn, RunResult, StepEvent
from app.audit import InMemoryAuditLog
from app.observability.run import AgentRunRecord, traced_agent_run
from app.observability.tracing import Tracer

# Builds the next agent's request from the results of the agents that already ran.
RequestBuilder = Callable[[Mapping[str, RunResult]], Any]


@dataclass(frozen=True, slots=True)
class ChainStep:
    """One link: which agent to run and how to derive its request from prior output."""

    label: str
    orchestrator: BaseOrchestrator[Any]
    build_request: RequestBuilder


@dataclass
class ChainResult:
    """Outcome of running a cross-agent chain."""

    results: dict[str, RunResult]
    order: list[str]
    events: list[StepEvent] = field(default_factory=list)
    records: list[AgentRunRecord] = field(default_factory=list)

    def outputs(self, label: str) -> dict[str, Any]:
        """The step outputs of the agent that ran under ``label``."""
        return self.results[label].outputs


async def run_chain(
    steps: list[ChainStep],
    *,
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    tracer: Tracer | None = None,
    emit: EmitFn | None = None,
    correlation_id: str | None = None,
) -> ChainResult:
    """Run ``steps`` in order, threading each agent's output to the next.

    Each link's events are forwarded with a ``<label>/<step>`` prefix so the caller
    can tell which agent produced which event. Labels must be unique.
    """
    labels = [s.label for s in steps]
    if len(labels) != len(set(labels)):
        raise ValueError("chain step labels must be unique")

    tracer = tracer or Tracer()
    chain = ChainResult(results={}, order=[], events=[], records=[])

    for step in steps:
        request = step.build_request(chain.results)

        async def _emit(event: StepEvent, _label: str = step.label) -> None:
            tagged = StepEvent(
                step=f"{_label}/{event.step}", status=event.status, detail=event.detail
            )
            chain.events.append(tagged)
            if emit is not None:
                await emit(tagged)

        record = await traced_agent_run(
            step.orchestrator,
            request,
            tracer=tracer,
            audit=audit,
            gateway=gateway,
            emit=_emit,
            correlation_id=correlation_id,
            actor=step.label,
        )
        chain.results[step.label] = record.result
        chain.order.append(step.label)
        chain.records.append(record)

    return chain
