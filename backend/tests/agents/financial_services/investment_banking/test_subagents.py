"""Subagent-level tests for Investment Banking — mocked gateway + fake connectors.

The load-bearing financial-services rule is exercised here: the client-facing
launch is a **consequential** action, gated behind a **mandatory compliance gate**
(conflicts / MNPI wall-crossing). Execution is blocked when the gate denies AND
held (default-deny) until a human approves.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.investment_banking.subagents import (
    GATE_DENY,
    GATE_PASS,
    ComplianceGateSubagent,
    CoverageOriginationSubagent,
    EcmDcmLevfinSubagent,
    LaunchMandateTool,
    MaExecutionSubagent,
    MaterialsDraftingSubagent,
    ModelingDiligenceSubagent,
    RestructuringSubagent,
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


# --- coverage-origination --------------------------------------------------


async def test_coverage_origination_qualifies_mandate() -> None:
    out = await CoverageOriginationSubagent("d1", "acme", "tech", _gateway()).execute(_ctx({}))
    assert out["qualified"] is True
    assert out["client"] == "acme"
    assert out["sector"] == "tech"


async def test_coverage_tailors_idea_to_relationship_and_momentum() -> None:
    connectors = _connectors(
        **{"client:rating:acme": "0.8", "sector:momentum:tech": "1"}
    )
    out = await CoverageOriginationSubagent(
        "d1", "acme", "tech", _gateway(), connectors
    ).execute(_ctx({}))
    # positive sector momentum -> capital-markets idea; strong relationship -> high priority
    assert out["recommended_product"] == "ecm-dcm-levfin"
    assert out["priority"] == "high"
    assert out["ideas"] == ["ecm-dcm-levfin"]


async def test_coverage_recommends_ma_when_momentum_soft() -> None:
    connectors = _connectors(**{"client:rating:acme": "0.3", "sector:momentum:tech": "0"})
    out = await CoverageOriginationSubagent(
        "d1", "acme", "tech", _gateway(), connectors
    ).execute(_ctx({}))
    assert out["recommended_product"] == "ma-execution"
    assert out["priority"] == "standard"


# --- modeling-diligence ----------------------------------------------------


async def test_modeling_diligence_reads_financials_and_values() -> None:
    connectors = _connectors(**{"financials:d1": "500"})
    out = await ModelingDiligenceSubagent("d1", _gateway(), connectors).execute(
        _ctx({"coverage-origination": {"qualified": True}})
    )
    assert out["enterprise_value"] == pytest.approx(500.0)
    assert out["valuation_ready"] is True


async def test_modeling_diligence_defaults_missing_financials_to_zero() -> None:
    out = await ModelingDiligenceSubagent("dX", _gateway(), _connectors()).execute(
        _ctx({"coverage-origination": {"qualified": True}})
    )
    assert out["enterprise_value"] == pytest.approx(0.0)


async def test_modeling_diligence_builds_ev_from_ebitda_multiple() -> None:
    connectors = _connectors(
        **{"ebitda:d1": "100", "multiple:d1": "8", "net_debt:d1": "150"}
    )
    out = await ModelingDiligenceSubagent("d1", _gateway(), connectors).execute(
        _ctx({"coverage-origination": {"qualified": True}})
    )
    assert out["method"] == "ebitda-multiple"
    assert out["enterprise_value"] == pytest.approx(800.0)
    assert out["equity_value"] == pytest.approx(650.0)


# --- materials-drafting ----------------------------------------------------


async def test_materials_drafting_builds_deck_from_valuation() -> None:
    out = await MaterialsDraftingSubagent(_gateway()).execute(
        _ctx({"modeling-diligence": {"enterprise_value": 500.0, "valuation_ready": True}})
    )
    assert out["deck_ready"] is True
    assert out["enterprise_value"] == pytest.approx(500.0)


async def test_materials_drafting_assembles_pitchbook_sections() -> None:
    out = await MaterialsDraftingSubagent(_gateway()).execute(
        _ctx(
            {
                "modeling-diligence": {
                    "enterprise_value": 500.0,
                    "equity_value": 350.0,
                    "method": "ebitda-multiple",
                    "valuation_ready": True,
                }
            }
        )
    )
    book = out["pitchbook"]
    assert "valuation" in book["sections"]
    assert book["page_count"] == len(book["sections"])
    assert book["valuation"]["equity_value"] == pytest.approx(350.0)


# --- compliance-gate (MANDATORY) -------------------------------------------


async def test_compliance_gate_passes_when_conflicts_clear() -> None:
    connectors = _connectors(**{"conflict:acme": "clear"})
    out = await ComplianceGateSubagent("acme", _gateway(), connectors).execute(
        _ctx({"modeling-diligence": {"valuation_ready": True}})
    )
    assert out["decision"] == GATE_PASS


async def test_compliance_gate_denies_when_conflict_flagged() -> None:
    connectors = _connectors(**{"conflict:acme": "flagged"})
    out = await ComplianceGateSubagent("acme", _gateway(), connectors).execute(
        _ctx({"modeling-diligence": {"valuation_ready": True}})
    )
    assert out["decision"] == GATE_DENY


async def test_compliance_gate_fails_closed_when_no_data() -> None:
    out = await ComplianceGateSubagent("ghost", _gateway(), _connectors()).execute(
        _ctx({"modeling-diligence": {"valuation_ready": True}})
    )
    assert out["decision"] == GATE_DENY


# --- launch tool / execution (consequential, gated) ------------------------


def test_launch_tool_is_consequential() -> None:
    assert LaunchMandateTool().consequential is True


def _exec_ctx(decision: str) -> StepContext:
    return _ctx(
        {
            "compliance-gate": {"decision": decision, "client": "acme"},
            "modeling-diligence": {"enterprise_value": 500.0},
        }
    )


async def test_execution_holds_launch_for_approval_when_gate_passes() -> None:
    guardrails = _guardrails()
    out = await MaExecutionSubagent("d1", guardrails).execute(_exec_ctx(GATE_PASS))
    assert out["blocked"] is False
    assert out["launched"] is False  # default-deny: held, not executed
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "ib_launch_mandate"


async def test_execution_blocked_when_gate_denies() -> None:
    guardrails = _guardrails()
    out = await MaExecutionSubagent("d1", guardrails).execute(_exec_ctx(GATE_DENY))
    assert out["blocked"] is True
    assert out["launched"] is False
    assert out["approval_id"] is None
    # nothing even reaches the guardrail queue — denied before any consequential call
    assert guardrails.pending() == []


async def test_ecm_and_restructuring_execution_share_the_gate_contract() -> None:
    for cls, kind in (
        (EcmDcmLevfinSubagent, "ecm-dcm-levfin"),
        (RestructuringSubagent, "restructuring"),
    ):
        guardrails = _guardrails()
        out = await cls("d1", guardrails).execute(_exec_ctx(GATE_DENY))  # type: ignore[abstract]
        assert out["kind"] == kind
        assert out["blocked"] is True
        assert guardrails.pending() == []
