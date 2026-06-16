"""Integration test: the Leadership/CFO agent invokes another enterprise agent.

End to end with a mocked Claude gateway and fake connectors: FP&A runs first, then
Leadership assembles the board pack from it. Asserts ordering, shared lineage, and
that the board-pack publication is held by the guardrail (default-deny).
"""

from __future__ import annotations

import pytest
from app.agents.core import ClaudeGateway
from app.audit import InMemoryAuditLog
from app.connectors import ToolRegistry, build_fake_connector
from app.guardrails import ApprovalState, GuardrailEngine
from app.integration import build_cfo_enterprise_chain, run_chain
from app.observability import Tracer


@pytest.fixture
def connectors() -> ToolRegistry:
    return build_fake_connector()


async def test_cfo_chain_runs_fpa_then_leadership_in_order(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_cfo_enterprise_chain(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        period="FY26-Q1",
        cost_centres=["cc1", "cc2"],
        divisions=["markets", "banking"],
        correlation_id="cfo-run-1",
    )

    result = await run_chain(
        steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="cfo-run-1"
    )

    assert result.order == ["fpa", "leadership"]
    # Both agents produced outputs and Leadership's board pack was assembled.
    assert result.outputs("fpa")
    board = result.outputs("leadership")["board-investor-reporting"]
    assert board["pack"]["period"] == "FY26-Q1"


async def test_cfo_chain_board_pack_publication_is_gated(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_cfo_enterprise_chain(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        period="FY26-Q1",
        cost_centres=["cc1"],
        divisions=["markets"],
        correlation_id="cfo-run-2",
    )

    result = await run_chain(
        steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="cfo-run-2"
    )

    board = result.outputs("leadership")["board-investor-reporting"]
    assert board["published"] is False  # default-deny: not published until approved
    assert board["approval_id"] is not None
    request = guardrails.get(board["approval_id"])
    assert request.state is ApprovalState.PENDING

    # The human approves -> the held publication now executes.
    outcome = await guardrails.approve(board["approval_id"], approver="cfo@firm")
    assert outcome.executed is True


async def test_cfo_chain_forwards_tagged_events_to_an_outer_sink(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    from app.agents.core import StepEvent

    received: list[StepEvent] = []

    async def sink(event: StepEvent) -> None:
        received.append(event)

    steps = build_cfo_enterprise_chain(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        period="FY26-Q1",
        cost_centres=["cc1"],
        divisions=["markets"],
        correlation_id="cfo-run-4",
    )
    result = await run_chain(
        steps,
        gateway=gateway,
        audit=audit,
        tracer=tracer,
        emit=sink,
        correlation_id="cfo-run-4",
    )

    assert received, "outer emit sink received no events"
    # Events are namespaced by the agent label that produced them.
    assert any(e.step.startswith("fpa/") for e in received)
    assert any(e.step.startswith("leadership/") for e in received)
    assert received == result.events


async def test_cfo_chain_emits_a_span_and_audit_event_per_agent(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_cfo_enterprise_chain(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        period="FY26-Q1",
        cost_centres=["cc1"],
        divisions=["markets"],
        correlation_id="cfo-run-3",
    )

    await run_chain(steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="cfo-run-3")

    run_spans = [s for s in tracer.spans if s.name.startswith("agent.run:")]
    assert {s.name for s in run_spans} == {"agent.run:fpa", "agent.run:leadership"}
    for span in run_spans:
        assert span.attributes["calls"] >= 1
        assert span.duration > 0

    run_events = [e for e in await audit.events() if e.action == "agent.run"]
    assert len(run_events) == 2
    assert all(e.correlation_id == "cfo-run-3" for e in run_events)
