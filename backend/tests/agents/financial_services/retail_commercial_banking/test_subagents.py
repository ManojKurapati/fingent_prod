"""Subagent-level tests for Retail & Commercial Banking.

Covers the three intake channels, loan origination, credit analysis, the
underwriting credit-policy decision (DSR/LTV against appetite), and the
consequential funding step proving no loan is funded unless underwriting approves.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.retail_commercial_banking.subagents import (
    BranchOpsSubagent,
    CommercialRmSubagent,
    CreditAnalysisSubagent,
    FundLoanTool,
    LoanFundingSubagent,
    LoanOriginationSubagent,
    PersonalBankingSubagent,
    UnderwritingSubagent,
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


# --- intake channels ------------------------------------------------------


async def test_personal_banking_intake() -> None:
    out = await PersonalBankingSubagent("ann", _gateway()).execute(_ctx({}))
    assert out["channel"] == "personal"
    assert out["applicant"] == "ann"


async def test_commercial_rm_intake() -> None:
    out = await CommercialRmSubagent("acme-ltd", _gateway()).execute(_ctx({}))
    assert out["channel"] == "commercial"


async def test_branch_ops_intake() -> None:
    out = await BranchOpsSubagent("walkin", _gateway()).execute(_ctx({}))
    assert out["channel"] == "branch"


# --- origination / credit analysis ----------------------------------------


async def test_loan_origination_prequalifies() -> None:
    connectors = _connectors(**{"bank:income:a1": "100"})
    out = await LoanOriginationSubagent("a1", _gateway(), connectors).execute(_ctx({}))
    assert out["pre_qualified"] is True
    assert out["application_id"] == "a1"


async def test_credit_analysis_assigns_rating() -> None:
    connectors = _connectors(**{"bank:income:a1": "120", "bank:debt_service:a1": "24"})
    out = await CreditAnalysisSubagent("a1", _gateway(), connectors).execute(_ctx({}))
    assert "risk_rating" in out
    assert out["risk_rating"] in {"A", "B", "C"}


# --- underwriting (credit-policy gate decision) ---------------------------


async def test_underwriting_approves_within_policy() -> None:
    # DSR 0.2 (<=0.4) and LTV 0.5 (<=0.8) -> approve
    connectors = _connectors(
        **{"bank:income:a1": "100", "bank:debt_service:a1": "20", "bank:collateral:a1": "200"}
    )
    out = await UnderwritingSubagent("a1", 100.0, _gateway(), connectors).execute(_ctx({}))
    assert out["decision"] == "approve"
    assert out["dsr"] <= 0.4
    assert out["ltv"] <= 0.8


async def test_underwriting_declines_when_dsr_too_high() -> None:
    # DSR 0.6 (>0.4) -> decline
    connectors = _connectors(
        **{"bank:income:a1": "100", "bank:debt_service:a1": "60", "bank:collateral:a1": "500"}
    )
    out = await UnderwritingSubagent("a1", 100.0, _gateway(), connectors).execute(_ctx({}))
    assert out["decision"] == "decline"


async def test_underwriting_declines_when_ltv_too_high() -> None:
    # LTV 0.95 (>0.8) -> decline
    connectors = _connectors(
        **{"bank:income:a1": "100", "bank:debt_service:a1": "10", "bank:collateral:a1": "100"}
    )
    out = await UnderwritingSubagent("a1", 95.0, _gateway(), connectors).execute(_ctx({}))
    assert out["decision"] == "decline"


# --- funding (consequential lend, gated by the underwriting decision) -----


async def test_fund_loan_tool_is_consequential() -> None:
    assert FundLoanTool().consequential is True


async def test_funding_blocked_when_underwriting_declines() -> None:
    guardrails = _guardrails()
    out = await LoanFundingSubagent("a1", guardrails).execute(
        _ctx({"underwriting": {"decision": "decline"}})
    )
    assert out["funded"] is False
    assert out["blocked"] is True
    assert out["approval_id"] is None
    # a declined application proposes no disbursement at all
    assert guardrails.pending() == []


async def test_funding_held_for_approval_when_underwriting_approves() -> None:
    guardrails = _guardrails()
    out = await LoanFundingSubagent("a1", guardrails).execute(
        _ctx({"underwriting": {"decision": "approve"}})
    )
    # gate APPROVE still requires a human underwriter sign-off (default-deny)
    assert out["funded"] is False
    assert out["blocked"] is False
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "banking_fund_loan"
