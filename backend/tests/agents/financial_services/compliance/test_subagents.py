"""Subagent-level tests for the Compliance, Legal & Financial Crime group-agent.

Screening reads per-subject status from fake connectors; the fraud-investigation
join dispositions any hit. The SAR-filing tool is consequential, and the
synchronous compliance gate other agents call is fail-closed.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.compliance.subagents import (
    AmlKycSubagent,
    ComplianceMonitoringSubagent,
    FileSarTool,
    FraudInvestigationSubagent,
    LegalCounselSubagent,
    RegulatoryAffairsSubagent,
    SanctionsScreeningSubagent,
    compliance_gate,
)
from app.connectors import FakeStore, build_fake_connector


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _gateway() -> ClaudeGateway:
    return ClaudeGateway(transport=_stub)


async def _noop(_: StepEvent) -> None:
    return None


def _ctx(results: dict[str, Any]) -> StepContext:
    return StepContext(step="t", results=results, emit=_noop)


def _connectors(**store: str) -> Any:
    return build_fake_connector(store=FakeStore(data=dict(store)))


# --- aml/kyc --------------------------------------------------------------


async def test_aml_kyc_clears_low_risk() -> None:
    out = await AmlKycSubagent(
        "cust1", _gateway(), _connectors(**{"kycrisk:cust1": "low"})
    ).execute(_ctx({}))
    assert out["risk_rating"] == "low"
    assert out["hit"] is False


async def test_aml_kyc_hit_on_high_risk_default() -> None:
    # Conservative default: an unknown subject is treated as a high-risk hit.
    out = await AmlKycSubagent("unknown", _gateway(), _connectors()).execute(_ctx({}))
    assert out["hit"] is True


# --- sanctions ------------------------------------------------------------


async def test_sanctions_screening_clears_with_no_matches() -> None:
    out = await SanctionsScreeningSubagent(
        "cust1", _gateway(), _connectors(**{"sanctions:cust1": "0"})
    ).execute(_ctx({}))
    assert out["matches"] == 0
    assert out["hit"] is False


async def test_sanctions_screening_hit_on_match() -> None:
    out = await SanctionsScreeningSubagent(
        "badco", _gateway(), _connectors(**{"sanctions:badco": "2"})
    ).execute(_ctx({}))
    assert out["matches"] == 2
    assert out["hit"] is True


# --- fraud investigation (disposition join) -------------------------------


async def test_fraud_investigation_clears_when_no_hits() -> None:
    out = await FraudInvestigationSubagent().execute(
        _ctx({"aml-kyc": {"hit": False}, "sanctions-screening": {"hit": False}})
    )
    assert out["cleared"] is True
    assert out["escalated"] is False
    assert out["sar_recommended"] is False
    assert out["hits"] == []


async def test_fraud_investigation_escalates_on_any_hit() -> None:
    out = await FraudInvestigationSubagent().execute(
        _ctx({"aml-kyc": {"hit": False}, "sanctions-screening": {"hit": True}})
    )
    assert out["cleared"] is False
    assert out["escalated"] is True
    assert out["sar_recommended"] is True
    assert out["hits"] == ["sanctions-screening"]


# --- continuous functions -------------------------------------------------


async def test_compliance_monitoring_reports_open_incidents() -> None:
    out = await ComplianceMonitoringSubagent(_gateway(), _connectors(**{"incidents": "3"})).execute(
        _ctx({})
    )
    assert out["open_incidents"] == 3


async def test_regulatory_affairs_reports_pending_filings() -> None:
    out = await RegulatoryAffairsSubagent(_gateway(), _connectors(**{"filings": "2"})).execute(
        _ctx({})
    )
    assert out["pending_filings"] == 2


async def test_legal_counsel_reports_contracts_under_review() -> None:
    out = await LegalCounselSubagent(_gateway(), _connectors(**{"contracts": "5"})).execute(
        _ctx({})
    )
    assert out["contracts_under_review"] == 5


# --- the SAR tool is consequential ----------------------------------------


def test_file_sar_tool_is_consequential() -> None:
    assert FileSarTool().consequential is True


# --- synchronous compliance gate (PASS/HOLD/DENY) -------------------------


async def test_compliance_gate_pass_on_clear() -> None:
    decision = await compliance_gate(_connectors(**{"clearance:cust1": "clear"}), "cust1")
    assert decision.decision == "PASS"
    assert decision.token is not None


async def test_compliance_gate_hold_on_review() -> None:
    decision = await compliance_gate(_connectors(**{"clearance:cust1": "review"}), "cust1")
    assert decision.decision == "HOLD"
    assert decision.token is None


async def test_compliance_gate_deny_on_blocked() -> None:
    decision = await compliance_gate(_connectors(**{"clearance:badco": "blocked"}), "badco")
    assert decision.decision == "DENY"


async def test_compliance_gate_fail_closed_on_unknown_subject() -> None:
    decision = await compliance_gate(_connectors(), "ghost")
    assert decision.decision == "DENY"
