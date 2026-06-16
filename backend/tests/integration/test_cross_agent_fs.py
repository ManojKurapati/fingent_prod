"""Integration test: the financial-services chain research -> portfolio -> trading -> operations.

End to end with a mocked Claude gateway and fake connectors seeded so every
mandatory gate (mandate-risk, pre-trade-risk, trade-confirmation) PASSES — proving
the consequential actions reach the default-deny approval queue rather than
executing, and that one human approval per stage releases them.
"""

from __future__ import annotations

from app.agents.core import ClaudeGateway
from app.audit import InMemoryAuditLog
from app.connectors import ToolRegistry
from app.guardrails import ApprovalState, GuardrailEngine
from app.integration import build_fs_trade_chain, run_chain
from app.observability import Tracer


def _chain_args(
    gateway: ClaudeGateway, guardrails: GuardrailEngine, connectors: ToolRegistry
) -> dict[str, object]:
    return dict(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        dataset="prices-eod",
        portfolio_id="PORT-1",
        names=["AAA", "BBB"],
        account="ACC-1",
        book="DESK-1",
        correlation_id="fs-run-1",
    )


async def test_fs_chain_runs_four_agents_in_order(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    seeded_connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_fs_trade_chain(**_chain_args(gateway, guardrails, seeded_connectors))
    result = await run_chain(
        steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="fs-run-1"
    )

    assert result.order == ["research", "portfolio", "trading", "operations"]


async def test_fs_chain_gates_pass_and_consequential_actions_are_held(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    seeded_connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_fs_trade_chain(**_chain_args(gateway, guardrails, seeded_connectors))
    result = await run_chain(
        steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="fs-run-1"
    )

    # Portfolio: mandate-risk gate PASS -> placement held, not executed.
    portfolio = result.outputs("portfolio")
    assert portfolio["mandate-risk-gate"]["decision"] == "PASS"
    assert portfolio["buyside-execution"]["blocked"] is False
    assert portfolio["buyside-execution"]["placed"] is False
    assert portfolio["buyside-execution"]["approval_id"] is not None

    # Trading: pre-trade-risk gate PASS -> routing held, not executed.
    trading = result.outputs("trading")
    assert trading["pre-trade-risk-gate"]["decision"] == "PASS"
    assert trading["execution-algo"]["blocked"] is False
    assert trading["execution-algo"]["routed"] is False
    assert trading["execution-algo"]["approval_id"] is not None

    # Operations: trade confirmed -> settlement held, not executed.
    operations = result.outputs("operations")
    assert operations["trade-support"]["confirmed"] is True
    assert operations["settlements"]["executed"] is False
    assert operations["settlements"]["approval_id"] is not None

    # Three consequential actions, all default-denied and pending.
    pending = guardrails.pending()
    assert len(pending) == 3
    assert all(p.state is ApprovalState.PENDING for p in pending)


async def test_fs_chain_releases_actions_on_approval(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    seeded_connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_fs_trade_chain(**_chain_args(gateway, guardrails, seeded_connectors))
    result = await run_chain(
        steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="fs-run-1"
    )

    route_id = result.outputs("trading")["execution-algo"]["approval_id"]
    outcome = await guardrails.approve(route_id, approver="trader@firm")
    assert outcome.executed is True
    assert outcome.output == "routed:ord-PORT-1"


async def test_fs_chain_every_agent_run_traced_and_audited(
    gateway: ClaudeGateway,
    audit: InMemoryAuditLog,
    guardrails: GuardrailEngine,
    seeded_connectors: ToolRegistry,
    tracer: Tracer,
) -> None:
    steps = build_fs_trade_chain(**_chain_args(gateway, guardrails, seeded_connectors))
    await run_chain(steps, gateway=gateway, audit=audit, tracer=tracer, correlation_id="fs-run-1")

    run_spans = {s.name for s in tracer.spans if s.name.startswith("agent.run:")}
    # research + portfolio (asset-investment-management) + trading + operations
    assert run_spans == {
        "agent.run:quant",
        "agent.run:asset-investment-management",
        "agent.run:sales-trading-markets",
        "agent.run:ops",
    }
    run_events = [e for e in await audit.events() if e.action == "agent.run"]
    assert len(run_events) == 4
    assert all(e.correlation_id == "fs-run-1" for e in run_events)
