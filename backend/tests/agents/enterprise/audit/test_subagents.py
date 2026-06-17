"""Subagent-level tests for Internal Audit & Controls.

Each subagent is exercised in isolation with a hand-built :class:`StepContext`
carrying its declared dependencies' outputs. Numeric/status inputs come from fake
connectors; the Claude gateway is mocked. The only consequential action — issuing
(publishing) the audit report — is routed through the guardrail engine.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.audit.subagents import (
    AuditPlanningSubagent,
    ControlTestSubagent,
    FindingsReportingSubagent,
    PublishFindingsTool,
    RemediationTrackingSubagent,
    SoxControlsSubagent,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text=f"[{model}] ok", input_tokens=3, output_tokens=2)


def _gateway() -> ClaudeGateway:
    return ClaudeGateway(transport=_stub_transport)


def _guardrails() -> GuardrailEngine:
    return GuardrailEngine(audit=InMemoryAuditLog())


async def _noop(_: StepEvent) -> None:
    return None


def _ctx(results: dict[str, Any]) -> StepContext:
    return StepContext(step="t", results=results, emit=_noop)


def _connectors(**store: str) -> Any:
    return build_fake_connector(store=FakeStore(data=dict(store)))


# --- audit-planning -------------------------------------------------------


async def test_audit_planning_scopes_controls() -> None:
    gw = _gateway()
    out = await AuditPlanningSubagent("FY26-rev", ["c1", "c2"], gw).execute(_ctx({}))
    assert out["engagement"] == "FY26-rev"
    assert out["scope"] == ["c1", "c2"]
    assert out["planned"] is True
    assert gw.usage.calls >= 1  # the model was consulted to risk-rank/scope


async def test_audit_planning_risk_ranks_and_prioritises() -> None:
    # c2 is the highest inherent risk; c3 is below the priority threshold.
    connectors = _connectors(**{"risk:c1": "0.6", "risk:c2": "0.9", "risk:c3": "0.2"})
    out = await AuditPlanningSubagent(
        "FY26-rev", ["c1", "c2", "c3"], _gateway(), connectors, risk_threshold=0.5
    ).execute(_ctx({}))
    assert out["risk_ranked"] == ["c2", "c1", "c3"]
    assert out["priority_controls"] == ["c2", "c1"]
    assert out["risk_scores"]["c2"] == 0.9


# --- control-test:<id> ----------------------------------------------------


async def test_control_test_passes_when_evidence_passes() -> None:
    connectors = _connectors(**{"evidence:c1": "pass"})
    out = await ControlTestSubagent("c1", _gateway(), connectors).execute(_ctx({}))
    assert out["control"] == "c1"
    assert out["passed"] is True
    assert out["deficiency"] is False


async def test_control_test_flags_deficiency_on_failed_evidence() -> None:
    connectors = _connectors(**{"evidence:c1": "fail"})
    out = await ControlTestSubagent("c1", _gateway(), connectors).execute(_ctx({}))
    assert out["passed"] is False
    assert out["deficiency"] is True


async def test_control_test_missing_evidence_is_a_deficiency() -> None:
    out = await ControlTestSubagent("cX", _gateway(), _connectors()).execute(_ctx({}))
    assert out["passed"] is False
    assert out["deficiency"] is True


# --- sox-controls ---------------------------------------------------------


async def test_sox_controls_collects_deficiencies() -> None:
    connectors = _connectors(**{"sox:c1": "effective", "sox:c2": "deficient"})
    out = await SoxControlsSubagent(["c1", "c2"], _gateway(), connectors).execute(_ctx({}))
    assert out["assessed"] == 2
    assert out["deficiencies"] == ["c2"]
    assert out["severity"] == "high"


async def test_sox_controls_clean_when_all_effective() -> None:
    connectors = _connectors(**{"sox:c1": "effective"})
    out = await SoxControlsSubagent(["c1"], _gateway(), connectors).execute(_ctx({}))
    assert out["deficiencies"] == []
    assert out["severity"] == "none"


# --- findings-reporting (consequential publish gate) ----------------------


def _testing_results() -> dict[str, Any]:
    return {
        "control-test:c1": {"control": "c1", "passed": False, "deficiency": True},
        "control-test:c2": {"control": "c2", "passed": True, "deficiency": False},
        "sox-controls": {"deficiencies": ["c3"], "severity": "high"},
    }


async def test_findings_reporting_synthesises_and_gates_publish() -> None:
    guardrails = _guardrails()
    out = await FindingsReportingSubagent("FY26-rev", guardrails).execute(_ctx(_testing_results()))
    assert out["control_failures"] == ["c1"]
    assert out["sox_deficiencies"] == ["c3"]
    assert sorted(out["findings"]) == ["c1", "c3"]
    # report issuance is consequential: held for CAE approval, never auto-published
    assert out["published"] is False
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "audit_publish_findings"
    assert pending[0].approver_role == "cae"


async def test_findings_reporting_gates_even_with_no_deficiencies() -> None:
    """Issuing any assurance report is consequential, regardless of result."""
    guardrails = _guardrails()
    clean = {
        "control-test:c1": {"control": "c1", "passed": True, "deficiency": False},
        "sox-controls": {"deficiencies": [], "severity": "none"},
    }
    out = await FindingsReportingSubagent("FY26-rev", guardrails).execute(_ctx(clean))
    assert out["findings"] == []
    assert len(guardrails.pending()) == 1  # default-deny still holds the publish


async def test_publish_findings_tool_is_consequential() -> None:
    assert PublishFindingsTool().consequential is True


# --- remediation-tracking -------------------------------------------------


async def test_remediation_tracking_opens_items_for_findings() -> None:
    out = await RemediationTrackingSubagent().execute(
        _ctx({"findings-reporting": {"findings": ["c1", "c3"]}})
    )
    assert out["open"] == 2
    assert out["items"] == ["c1", "c3"]
    assert out["status"] == "tracking"


async def test_remediation_tracking_clean_when_no_findings() -> None:
    out = await RemediationTrackingSubagent().execute(
        _ctx({"findings-reporting": {"findings": []}})
    )
    assert out["open"] == 0
    assert out["status"] == "clean"


async def test_remediation_tracking_closes_items_from_tracker() -> None:
    connectors = _connectors(**{"remediation:c1": "closed", "remediation:c3": "in_progress"})
    out = await RemediationTrackingSubagent(connectors).execute(
        _ctx({"findings-reporting": {"findings": ["c1", "c3"]}})
    )
    assert out["closed"] == 1
    assert out["closed_items"] == ["c1"]
    assert out["open"] == 1
    assert out["items"] == ["c3"]
    assert out["status"] == "tracking"


async def test_remediation_tracking_reaches_closed_when_all_remediated() -> None:
    connectors = _connectors(**{"remediation:c1": "closed", "remediation:c3": "closed"})
    out = await RemediationTrackingSubagent(connectors).execute(
        _ctx({"findings-reporting": {"findings": ["c1", "c3"]}})
    )
    assert out["open"] == 0
    assert out["closed"] == 2
    assert out["status"] == "closed"
