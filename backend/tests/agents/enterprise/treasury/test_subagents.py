"""Subagent-level tests for Treasury — mocked Claude gateway + fake connectors.

Numeric inputs (bank balances, AR/AP, exposures, debt) come from a fake connector
store; the gateway is mocked. The consequential cash-movement actions (sweep and
hedge execution) are gated via dedicated guardrail tools, tested in the router and
orchestrator suites.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.treasury.subagents import (
    BankConnectivitySubagent,
    CashPositioningSubagent,
    DebtCovenantsSubagent,
    ExecuteHedgeTool,
    ExecuteSweepTool,
    FxHedgingSubagent,
    LiquidityForecastingSubagent,
)
from app.connectors import FakeStore, build_fake_connector


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text=f"[{model}] ok", input_tokens=3, output_tokens=2)


def _gateway() -> ClaudeGateway:
    return ClaudeGateway(transport=_stub_transport)


async def _noop(_: StepEvent) -> None:
    return None


def _ctx(results: dict[str, Any]) -> StepContext:
    return StepContext(step="t", results=results, emit=_noop)


def _connectors(**store: str) -> Any:
    return build_fake_connector(store=FakeStore(data=dict(store)))


# --- cash-positioning (sequential head) -----------------------------------


async def test_cash_positioning_sums_balances_and_reconciles() -> None:
    gw = _gateway()
    connectors = _connectors(
        **{"balance:a1": "1000", "balance:a2": "500", "bank:a1": "1000", "bank:a2": "500"}
    )
    out = await CashPositioningSubagent(["a1", "a2"], gw, connectors).execute(_ctx({}))
    assert out["position"] == pytest.approx(1500.0)
    assert out["by_account"] == {"a1": 1000.0, "a2": 500.0}
    assert out["reconciled"] is True
    assert gw.usage.calls >= 1


async def test_cash_positioning_flags_unreconciled_account() -> None:
    connectors = _connectors(**{"balance:a1": "1000", "bank:a1": "900"})
    out = await CashPositioningSubagent(["a1"], _gateway(), connectors).execute(_ctx({}))
    assert out["reconciled"] is False
    assert out["breaks"] == ["a1"]


# --- liquidity-forecasting (needs the cash position) ----------------------


async def test_liquidity_forecasting_projects_from_position_and_working_capital() -> None:
    connectors = _connectors(**{"ar": "400", "ap": "150"})
    out = await LiquidityForecastingSubagent(_gateway(), connectors, min_buffer=1000.0).execute(
        _ctx({"cash-positioning": {"position": 1500.0}})
    )
    # forecast = position + AR - AP = 1500 + 400 - 150 = 1750
    assert out["forecast"] == pytest.approx(1750.0)
    assert out["working_capital"] == pytest.approx(250.0)
    assert out["above_buffer"] is True


async def test_liquidity_forecasting_flags_buffer_breach() -> None:
    connectors = _connectors(**{"ar": "0", "ap": "800"})
    out = await LiquidityForecastingSubagent(_gateway(), connectors, min_buffer=1000.0).execute(
        _ctx({"cash-positioning": {"position": 1500.0}})
    )
    assert out["forecast"] == pytest.approx(700.0)
    assert out["above_buffer"] is False


# --- fx-hedging (parallel tail; needs the forecast) -----------------------


async def test_fx_hedging_proposes_hedge_off_net_exposure() -> None:
    connectors = _connectors(**{"fx:EUR": "300", "fx:GBP": "200"})
    out = await FxHedgingSubagent(["EUR", "GBP"], _gateway(), connectors).execute(
        _ctx({"liquidity-forecasting": {"forecast": 1750.0}})
    )
    assert out["net_exposure"] == pytest.approx(500.0)
    assert out["proposed_hedge"] == pytest.approx(500.0)
    # the daily run only PROPOSES; execution is a separate gated endpoint
    assert out["executed"] is False


# --- debt-covenants (parallel tail; needs the forecast) -------------------


async def test_debt_covenants_computes_leverage_and_headroom() -> None:
    connectors = _connectors(**{"debt": "2000", "ebitda": "1000"})
    out = await DebtCovenantsSubagent(_gateway(), connectors, max_leverage=3.0).execute(
        _ctx({"liquidity-forecasting": {"forecast": 1750.0}})
    )
    assert out["leverage"] == pytest.approx(2.0)
    assert out["headroom"] == pytest.approx(1.0)
    assert out["compliant"] is True


async def test_debt_covenants_flags_breach() -> None:
    connectors = _connectors(**{"debt": "4000", "ebitda": "1000"})
    out = await DebtCovenantsSubagent(_gateway(), connectors, max_leverage=3.0).execute(
        _ctx({"liquidity-forecasting": {"forecast": 1750.0}})
    )
    assert out["leverage"] == pytest.approx(4.0)
    assert out["compliant"] is False


# --- bank-connectivity (standing service, runs in parallel) ---------------


async def test_bank_connectivity_reports_active_banks() -> None:
    connectors = _connectors(**{"active_banks": "3"})
    out = await BankConnectivitySubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["active_banks"] == 3
    assert out["status"] == "ok"


# --- consequential cash-movement tools ------------------------------------


async def test_sweep_and_hedge_tools_are_consequential() -> None:
    assert ExecuteSweepTool().consequential is True
    assert ExecuteHedgeTool().consequential is True
