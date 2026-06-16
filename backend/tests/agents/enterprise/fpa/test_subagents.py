"""Subagent-level tests for FP&A — mocked Claude gateway + fake connectors.

Each subagent is exercised in isolation with a hand-built :class:`StepContext`
carrying its declared dependencies' outputs.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.fpa.subagents import (
    BudgetConsolidationSubagent,
    DataIntakeSubagent,
    ForecastEngineSubagent,
    ReportingPacksSubagent,
    RequestCommentaryTool,
    RevenueAnalyticsSubagent,
    ScenarioModellingSubagent,
    VarianceSubagent,
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


# --- data-intake ----------------------------------------------------------


async def test_data_intake_reads_actuals_and_validates() -> None:
    gw = _gateway()
    connectors = _connectors(**{"actual:cc1": "120", "actual:cc2": "80"})
    out = await DataIntakeSubagent("FY26", ["cc1", "cc2"], gw, connectors).execute(_ctx({}))
    assert out["validated"] is True
    assert out["period"] == "FY26"
    assert out["actuals"] == {"cc1": 120.0, "cc2": 80.0}
    assert gw.usage.calls >= 1  # the model was consulted to validate intake


async def test_data_intake_defaults_missing_actuals_to_zero() -> None:
    out = await DataIntakeSubagent("FY26", ["ccX"], _gateway(), _connectors()).execute(_ctx({}))
    assert out["actuals"] == {"ccX": 0.0}


# --- budget-consolidation -------------------------------------------------


async def test_budget_consolidation_consolidates_plan() -> None:
    connectors = _connectors(**{"plan:cc1": "100", "plan:cc2": "100"})
    out = await BudgetConsolidationSubagent(["cc1", "cc2"], _gateway(), connectors).execute(
        _ctx({"data-intake": {"validated": True}})
    )
    assert out["plan"] == {"cc1": 100.0, "cc2": 100.0}
    assert out["total_plan"] == 200.0


# --- forecast-engine ------------------------------------------------------


async def test_forecast_engine_projects_from_plan() -> None:
    out = await ForecastEngineSubagent(["cc1"], _gateway()).execute(
        _ctx({"budget-consolidation": {"plan": {"cc1": 100.0}}})
    )
    assert out["forecast"]["cc1"] == pytest.approx(105.0)


# --- revenue-analytics ----------------------------------------------------


async def test_revenue_analytics_reports_arr() -> None:
    out = await RevenueAnalyticsSubagent(["cc1", "cc2"], _gateway()).execute(
        _ctx({"budget-consolidation": {"total_plan": 200.0}})
    )
    assert out["arr"] == pytest.approx(200.0)
    assert "by_segment" in out


# --- scenario-modelling ---------------------------------------------------


async def test_scenario_modelling_applies_drivers_to_actual_base() -> None:
    out = await ScenarioModellingSubagent("FY26", {"price": 0.1}, _gateway()).execute(
        _ctx({"data-intake": {"actuals": {"cc1": 120.0, "cc2": 80.0}}})
    )
    assert out["base"] == pytest.approx(200.0)
    assert out["adjusted"] == pytest.approx(220.0)
    assert out["drivers"] == {"price": 0.1}


# --- variance:<cc> (consequential variance commentary) --------------------


def _variance_ctx(actual: float, plan: float) -> StepContext:
    return _ctx(
        {
            "data-intake": {"actuals": {"cc1": actual}},
            "budget-consolidation": {"plan": {"cc1": plan}},
        }
    )


async def test_variance_breach_requests_commentary_via_guardrail_default_deny() -> None:
    guardrails = _guardrails()
    out = await VarianceSubagent("cc1", guardrails, threshold=0.1).execute(
        _variance_ctx(actual=120.0, plan=100.0)
    )
    assert out["cost_centre"] == "cc1"
    assert out["variance"] == pytest.approx(0.2)
    assert out["breach"] is True
    assert out["commentary_requested"] is True
    assert out["approval_id"] is not None
    # default-deny: the external "ping owner" action is held, not executed
    assert len(guardrails.pending()) == 1
    assert guardrails.pending()[0].tool_name == "fpa_request_commentary"


async def test_variance_within_threshold_does_not_request_commentary() -> None:
    guardrails = _guardrails()
    out = await VarianceSubagent("cc1", guardrails, threshold=0.1).execute(
        _variance_ctx(actual=105.0, plan=100.0)
    )
    assert out["breach"] is False
    assert out["commentary_requested"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []


async def test_request_commentary_tool_is_consequential() -> None:
    assert RequestCommentaryTool().consequential is True


# --- reporting-packs (fan-in) ---------------------------------------------


async def test_reporting_pack_assembles_sections_and_breaches() -> None:
    results = {
        "forecast-engine": {"forecast": {"cc1": 105.0}},
        "revenue-analytics": {"arr": 200.0},
        "scenario-modelling": {"base": 200.0, "adjusted": 220.0},
        "variance:cc1": {"cost_centre": "cc1", "variance": 0.2, "breach": True},
        "variance:cc2": {"cost_centre": "cc2", "variance": 0.05, "breach": False},
    }
    out = await ReportingPacksSubagent().execute(_ctx(results))
    assert out["pack"]["cost_centres"] == 2
    assert out["breaches"] == ["cc1"]
    assert out["sections"] >= 3  # forecast + revenue + scenario at minimum
