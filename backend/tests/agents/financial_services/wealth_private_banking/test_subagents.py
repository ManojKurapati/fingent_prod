"""Subagent-level tests for Wealth & Private Banking.

Covers the KYC entry gate, parallel planning/advice (skipped until KYC clears),
the suitability and credit gates, and the two consequential actions — discretionary
rebalance and Lombard credit — proving each is blocked unless its gate PASSes.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.wealth_private_banking.subagents import (
    ClientOnboardingKycSubagent,
    CreditGateSubagent,
    DiscretionaryPmSubagent,
    ExtendCreditTool,
    FinancialPlanningSubagent,
    InvestmentAdviceSubagent,
    PlanReconciliationSubagent,
    PrivateBankingSubagent,
    RebalanceTool,
    SuitabilityGateSubagent,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text=f"[{model}] ok", input_tokens=2, output_tokens=2)


def _gateway() -> ClaudeGateway:
    return ClaudeGateway(transport=_stub)


def _guardrails() -> GuardrailEngine:
    return GuardrailEngine(audit=InMemoryAuditLog())


async def _noop(_: StepEvent) -> None:
    return None


def _ctx(results: dict[str, Any]) -> StepContext:
    return StepContext(step="t", results=results, emit=_noop)


def _connectors(**store: str) -> Any:
    return build_fake_connector(store=FakeStore(data=dict(store)))


# --- client onboarding / KYC entry gate -----------------------------------


async def test_onboarding_clears_clean_client() -> None:
    out = await ClientOnboardingKycSubagent("c1", _gateway(), _connectors()).execute(_ctx({}))
    assert out["kyc_cleared"] is True
    assert out["client_id"] == "c1"


async def test_onboarding_blocks_sanctioned_client() -> None:
    connectors = _connectors(**{"wealth:sanctions_hit:c1": "1"})
    out = await ClientOnboardingKycSubagent("c1", _gateway(), connectors).execute(_ctx({}))
    assert out["kyc_cleared"] is False


# --- planning / advice (no advice before KYC clears) ----------------------


async def test_financial_planning_runs_after_kyc_clears() -> None:
    out = await FinancialPlanningSubagent("c1", _gateway(), _connectors()).execute(
        _ctx({"client-onboarding-kyc": {"kyc_cleared": True}})
    )
    assert out["skipped"] is False
    assert "plan" in out


async def test_financial_planning_skipped_when_kyc_not_cleared() -> None:
    out = await FinancialPlanningSubagent("c1", _gateway(), _connectors()).execute(
        _ctx({"client-onboarding-kyc": {"kyc_cleared": False}})
    )
    assert out["skipped"] is True
    assert "plan" not in out


async def test_investment_advice_skipped_when_kyc_not_cleared() -> None:
    out = await InvestmentAdviceSubagent("c1", _gateway()).execute(
        _ctx({"client-onboarding-kyc": {"kyc_cleared": False}})
    )
    assert out["skipped"] is True


async def test_plan_reconciliation_joins_plan_and_advice() -> None:
    out = await PlanReconciliationSubagent().execute(
        _ctx(
            {
                "financial-planning": {"skipped": False, "plan": {"goal": "retire"}},
                "investment-advice": {"skipped": False, "allocation": {"equity": 0.6}},
            }
        )
    )
    assert out["reconciled"] is True


# --- suitability gate + discretionary rebalance (consequential) -----------


async def test_rebalance_tool_is_consequential() -> None:
    assert RebalanceTool().consequential is True


async def test_suitability_gate_passes_within_tolerance() -> None:
    connectors = _connectors(**{"wealth:risk_tolerance:c1": "0.7"})
    out = await SuitabilityGateSubagent("c1", 0.5, connectors).execute(_ctx({}))
    assert out["decision"] == "PASS"


async def test_suitability_gate_denies_above_tolerance() -> None:
    connectors = _connectors(**{"wealth:risk_tolerance:c1": "0.4"})
    out = await SuitabilityGateSubagent("c1", 0.9, connectors).execute(_ctx({}))
    assert out["decision"] == "DENY"


async def test_rebalance_blocked_when_suitability_denies() -> None:
    guardrails = _guardrails()
    out = await DiscretionaryPmSubagent("c1", guardrails).execute(
        _ctx({"suitability-gate": {"decision": "DENY"}})
    )
    assert out["executed"] is False
    assert out["blocked"] is True
    assert out["approval_id"] is None
    # a denied suitability gate means no asset move is even proposed
    assert guardrails.pending() == []


async def test_rebalance_held_for_approval_when_suitability_passes() -> None:
    guardrails = _guardrails()
    out = await DiscretionaryPmSubagent("c1", guardrails).execute(
        _ctx({"suitability-gate": {"decision": "PASS"}})
    )
    # gate PASS still requires human sign-off — default-deny holds the asset move
    assert out["executed"] is False
    assert out["blocked"] is False
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "wealth_rebalance"


# --- credit gate + Lombard lending (consequential) ------------------------


async def test_extend_credit_tool_is_consequential() -> None:
    assert ExtendCreditTool().consequential is True


async def test_credit_gate_passes_within_ltv() -> None:
    connectors = _connectors(**{"wealth:collateral:c1": "1000"})
    out = await CreditGateSubagent("c1", 400.0, connectors).execute(_ctx({}))
    assert out["decision"] == "PASS"


async def test_credit_gate_denies_above_ltv() -> None:
    connectors = _connectors(**{"wealth:collateral:c1": "1000"})
    out = await CreditGateSubagent("c1", 800.0, connectors).execute(_ctx({}))
    assert out["decision"] == "DENY"


async def test_credit_blocked_when_gate_denies() -> None:
    guardrails = _guardrails()
    out = await PrivateBankingSubagent("c1", 800.0, guardrails).execute(
        _ctx({"credit-gate": {"decision": "DENY"}})
    )
    assert out["executed"] is False
    assert out["blocked"] is True
    assert guardrails.pending() == []


async def test_credit_held_for_approval_when_gate_passes() -> None:
    guardrails = _guardrails()
    out = await PrivateBankingSubagent("c1", 400.0, guardrails).execute(
        _ctx({"credit-gate": {"decision": "PASS"}})
    )
    assert out["executed"] is False
    assert out["approval_id"] is not None
    assert guardrails.pending()[0].tool_name == "wealth_extend_credit"
