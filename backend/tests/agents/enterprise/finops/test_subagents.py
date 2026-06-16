"""Subagent-level tests for Finance Systems & Operations.

Row counts, SoD-conflict flags and process KPIs come from fake connectors; the
Claude gateway is mocked. The only consequential action — applying an ERP access
change that introduces a segregation-of-duties conflict — is routed through the
guardrail engine (default-deny, feeds Internal Audit).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.finops.subagents import (
    AccessChangeTool,
    DashboardsReportingSubagent,
    DataPipelinesSubagent,
    ErpAdministrationSubagent,
    O2cP2pProcessOwnerSubagent,
    ProcessTransformationSubagent,
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


# --- data-pipelines (sequential spine head) -------------------------------


async def test_data_pipelines_reconciles_when_all_sources_present() -> None:
    gw = _gateway()
    connectors = _connectors(**{"rows:gl": "100", "rows:ap": "50"})
    out = await DataPipelinesSubagent(["gl", "ap"], gw, connectors).execute(_ctx({}))
    assert out["total_rows"] == 150.0
    assert out["by_source"] == {"gl": 100.0, "ap": 50.0}
    assert out["reconciled"] is True
    assert out["missing"] == []
    assert gw.usage.calls >= 1


async def test_data_pipelines_flags_missing_source() -> None:
    connectors = _connectors(**{"rows:gl": "100"})
    out = await DataPipelinesSubagent(["gl", "ap"], _gateway(), connectors).execute(_ctx({}))
    assert out["reconciled"] is False
    assert out["missing"] == ["ap"]


# --- dashboards-reporting -------------------------------------------------


async def test_dashboards_reporting_renders_from_reconciled_data() -> None:
    out = await DashboardsReportingSubagent(_gateway()).execute(
        _ctx({"data-pipelines": {"total_rows": 150.0, "reconciled": True}})
    )
    assert out["rows"] == 150.0
    assert out["anomaly"] is False
    assert "reconciliation" in out["dashboards"]


async def test_dashboards_reporting_flags_anomaly_when_unreconciled() -> None:
    out = await DashboardsReportingSubagent(_gateway()).execute(
        _ctx({"data-pipelines": {"total_rows": 0.0, "reconciled": False}})
    )
    assert out["anomaly"] is True


# --- erp-administration (consequential SoD gate) --------------------------


async def test_erp_admin_gates_sod_conflicting_change_default_deny() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"sod_conflict:grant-admin": "yes", "sod_conflict:grant-read": "no"})
    out = await ErpAdministrationSubagent(
        ["grant-admin", "grant-read"], _gateway(), guardrails, connectors
    ).execute(_ctx({}))
    assert out["requested"] == 2
    assert out["conflicts"] == ["grant-admin"]
    assert out["gated"] == 1
    assert out["approval_ids"]
    # default-deny: the conflicting change is held, not applied
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "finops_access_change"
    assert pending[0].approver_role == "sod-reviewer"


async def test_erp_admin_no_gate_when_no_conflict() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"sod_conflict:grant-read": "no"})
    out = await ErpAdministrationSubagent(
        ["grant-read"], _gateway(), guardrails, connectors
    ).execute(_ctx({}))
    assert out["conflicts"] == []
    assert out["gated"] == 0
    assert guardrails.pending() == []


async def test_erp_admin_no_changes_is_noop() -> None:
    guardrails = _guardrails()
    out = await ErpAdministrationSubagent([], _gateway(), guardrails, _connectors()).execute(
        _ctx({})
    )
    assert out["requested"] == 0
    assert guardrails.pending() == []


async def test_access_change_tool_is_consequential() -> None:
    assert AccessChangeTool().consequential is True


# --- process-transformation -----------------------------------------------


async def test_process_transformation_counts_opportunities() -> None:
    connectors = _connectors(**{"automation:candidates": "3"})
    out = await ProcessTransformationSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["opportunities"] == 3
    assert out["prioritised"] is True


async def test_process_transformation_defaults_to_zero() -> None:
    out = await ProcessTransformationSubagent(_gateway(), _connectors()).execute(_ctx({}))
    assert out["opportunities"] == 0
    assert out["prioritised"] is False


# --- o2c-p2p-process-owner ------------------------------------------------


async def test_o2c_p2p_reports_kpis_healthy() -> None:
    connectors = _connectors(**{"kpi:cycle_time": "4", "kpi:exceptions": "0"})
    out = await O2cP2pProcessOwnerSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["cycle_time"] == 4.0
    assert out["exceptions"] == 0.0
    assert out["healthy"] is True


async def test_o2c_p2p_unhealthy_when_exceptions() -> None:
    connectors = _connectors(**{"kpi:cycle_time": "9", "kpi:exceptions": "2"})
    out = await O2cP2pProcessOwnerSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["healthy"] is False
