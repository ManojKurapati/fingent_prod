"""Subagent-level tests for Leadership — mocked gateway + fake connectors.

Each subagent runs in isolation with a hand-built :class:`StepContext` carrying
its declared dependencies' outputs.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.leadership.subagents import (
    BoardInvestorReportingSubagent,
    BudgetPlanSignoffSubagent,
    CapitalStrategySubagent,
    DivisionalRollupSubagent,
    PublishBoardPackTool,
    TransformationSponsorSubagent,
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


# --- divisional-rollup -----------------------------------------------------


async def test_divisional_rollup_consolidates_group_pnl() -> None:
    gw = _gateway()
    connectors = _connectors(**{"pnl:emea": "100", "pnl:amer": "150"})
    out = await DivisionalRollupSubagent(["emea", "amer"], gw, connectors).execute(_ctx({}))
    assert out["divisions"] == {"emea": 100.0, "amer": 150.0}
    assert out["group_pnl"] == pytest.approx(250.0)
    assert gw.usage.calls >= 1


async def test_divisional_rollup_defaults_missing_division_to_zero() -> None:
    out = await DivisionalRollupSubagent(["ghost"], _gateway(), _connectors()).execute(_ctx({}))
    assert out["divisions"] == {"ghost": 0.0}
    assert out["group_pnl"] == pytest.approx(0.0)


# --- capital-strategy ------------------------------------------------------


async def test_capital_strategy_recommends_equity_when_overlevered() -> None:
    connectors = _connectors(**{"capital:debt": "60", "capital:equity": "40"})
    out = await CapitalStrategySubagent(0.4, _gateway(), connectors).execute(
        _ctx({"divisional-rollup": {"group_pnl": 250.0}})
    )
    assert out["leverage"] == pytest.approx(0.6)
    assert out["recommendation"] == "raise_equity"
    assert out["headroom"] == pytest.approx(-0.2)
    assert out["group_pnl"] == pytest.approx(250.0)


async def test_capital_strategy_recommends_debt_when_underlevered() -> None:
    connectors = _connectors(**{"capital:debt": "20", "capital:equity": "80"})
    out = await CapitalStrategySubagent(0.4, _gateway(), connectors).execute(
        _ctx({"divisional-rollup": {"group_pnl": 0.0}})
    )
    assert out["leverage"] == pytest.approx(0.2)
    assert out["recommendation"] == "raise_debt"


async def test_capital_strategy_handles_zero_capital_base() -> None:
    out = await CapitalStrategySubagent(0.4, _gateway(), _connectors()).execute(
        _ctx({"divisional-rollup": {"group_pnl": 0.0}})
    )
    assert out["leverage"] == pytest.approx(0.0)


# --- board-investor-reporting (consequential publish) ----------------------


async def test_board_reporting_holds_publish_via_guardrail_default_deny() -> None:
    guardrails = _guardrails()
    out = await BoardInvestorReportingSubagent("FY26", guardrails, _gateway()).execute(
        _ctx(
            {
                "divisional-rollup": {"group_pnl": 250.0},
                "capital-strategy": {"leverage": 0.6, "recommendation": "raise_equity"},
            }
        )
    )
    assert out["pack"]["group_pnl"] == pytest.approx(250.0)
    assert out["pack"]["recommendation"] == "raise_equity"
    assert out["published"] is False
    assert out["approval_id"] is not None
    # default-deny: the external board-pack publication is held, not executed
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "leadership_publish_board_pack"
    assert pending[0].approver_role == "cfo"


async def test_publish_board_pack_tool_is_consequential() -> None:
    assert PublishBoardPackTool().consequential is True


# --- budget-plan-signoff ---------------------------------------------------


async def test_budget_signoff_stages_variance_against_plan() -> None:
    connectors = _connectors(**{"budget:plan": "200"})
    out = await BudgetPlanSignoffSubagent(_gateway(), connectors).execute(
        _ctx({"divisional-rollup": {"group_pnl": 250.0}})
    )
    assert out["staged"] is True
    assert out["budget"] == pytest.approx(200.0)
    assert out["variance"] == pytest.approx(50.0)


# --- transformation-sponsor ------------------------------------------------


async def test_transformation_sponsor_tracks_initiative_count() -> None:
    connectors = _connectors(**{"initiatives:count": "3"})
    out = await TransformationSponsorSubagent(connectors, _gateway()).execute(_ctx({}))
    assert out["tracked"] is True
    assert out["initiatives"] == 3
