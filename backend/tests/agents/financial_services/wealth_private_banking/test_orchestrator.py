"""Orchestrator-graph tests for Wealth & Private Banking.

Asserts the hybrid onboarding shape (KYC entry gate -> parallel planning/advice ->
reconciliation), that planning/advice overlap concurrently, and that the two
action paths are sequential with the gate strictly before the consequential action.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.wealth_private_banking.orchestrator import (
    CreditOrchestrator,
    RebalanceOrchestrator,
    WealthOnboardingOrchestrator,
)
from app.agents.financial_services.wealth_private_banking.schemas import (
    CreditRequest,
    OnboardRequest,
    RebalanceRequest,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_PARALLEL_PROMPTS = {"financial planning", "investment advice"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(**store: str) -> ToolRegistry:
    return build_fake_connector(store=FakeStore(data=dict(store)))


def _onboarding(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> WealthOnboardingOrchestrator:
    return WealthOnboardingOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        connectors=connectors or _connectors(),
    )


# --- hybrid onboarding ----------------------------------------------------


def test_onboarding_graph_is_hybrid_kyc_then_parallel_then_reconcile() -> None:
    graph = _onboarding().build_graph(OnboardRequest(client_id="c1", segment="hnw", name="Ada"))
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["client-onboarding-kyc"].depends_on == ()
    assert by_name["financial-planning"].depends_on == ("client-onboarding-kyc",)
    assert by_name["investment-advice"].depends_on == ("client-onboarding-kyc",)
    assert set(by_name["plan-reconciliation"].depends_on) == {
        "financial-planning",
        "investment-advice",
    }


async def test_planning_and_advice_run_concurrently() -> None:
    barrier = asyncio.Barrier(len(_PARALLEL_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _PARALLEL_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch = _onboarding(transport=gated)
    result = await asyncio.wait_for(
        orch.run(OnboardRequest(client_id="c1", segment="hnw", name="Ada")), timeout=1.0
    )
    assert result.outputs["plan-reconciliation"]["reconciled"] is True


async def test_no_advice_before_kyc_clears() -> None:
    connectors = _connectors(**{"wealth:sanctions_hit:c1": "1"})
    orch = _onboarding(connectors=connectors)
    result = await orch.run(OnboardRequest(client_id="c1", segment="hnw", name="Ada"))
    assert result.outputs["client-onboarding-kyc"]["kyc_cleared"] is False
    assert result.outputs["financial-planning"]["skipped"] is True
    assert result.outputs["investment-advice"]["skipped"] is True


# --- sequential action paths (gate before consequential action) -----------


def test_rebalance_graph_is_sequential_gate_then_action() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = RebalanceOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_connectors(**{"wealth:risk_tolerance:c1": "0.7"}),
    )
    graph = orch.build_graph(RebalanceRequest(client_id="c1", proposed_risk=0.5))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["suitability-gate", "discretionary-pm"]


async def test_rebalance_blocked_end_to_end_when_unsuitable() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = RebalanceOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_connectors(**{"wealth:risk_tolerance:c1": "0.3"}),
    )
    result = await orch.run(RebalanceRequest(client_id="c1", proposed_risk=0.9))
    assert result.outputs["suitability-gate"]["decision"] == "DENY"
    assert result.outputs["discretionary-pm"]["blocked"] is True
    assert guardrails.pending() == []


async def test_rebalance_held_for_approval_when_suitable() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = RebalanceOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_connectors(**{"wealth:risk_tolerance:c1": "0.7"}),
    )
    result = await orch.run(RebalanceRequest(client_id="c1", proposed_risk=0.5))
    assert result.outputs["suitability-gate"]["decision"] == "PASS"
    assert result.outputs["discretionary-pm"]["approval_id"] is not None
    assert len(guardrails.pending()) == 1


def test_credit_graph_is_sequential_gate_then_action() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = CreditOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_connectors(**{"wealth:collateral:c1": "1000"}),
    )
    graph = orch.build_graph(CreditRequest(client_id="c1", loan_amount=400.0, facility="lombard"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["credit-gate", "private-banking"]


async def test_credit_blocked_end_to_end_when_over_ltv() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = CreditOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_connectors(**{"wealth:collateral:c1": "1000"}),
    )
    result = await orch.run(CreditRequest(client_id="c1", loan_amount=900.0, facility="lombard"))
    assert result.outputs["credit-gate"]["decision"] == "DENY"
    assert result.outputs["private-banking"]["blocked"] is True
    assert guardrails.pending() == []
