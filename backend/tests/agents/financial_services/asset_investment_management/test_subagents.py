"""Subagent-level tests for Asset & Investment Management.

The mandatory dependency is exercised here: a proposed rebalance is executed only
after the **mandate & risk gate** (limits / liquidity / suitability) clears.
Placing orders is a **consequential** action — blocked outright on a gate deny and
otherwise held (default-deny) for PM approval.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.asset_investment_management.subagents import (
    GATE_DENY,
    GATE_PASS,
    AssetAllocationSubagent,
    BuysideExecutionSubagent,
    BuysideResearchSubagent,
    MacroStrategySubagent,
    MandateRiskGateSubagent,
    PlaceOrdersTool,
    PortfolioConstructionSubagent,
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


# --- macro-strategy -> asset-allocation (sequential spine) -----------------


async def test_macro_strategy_produces_house_view() -> None:
    out = await MacroStrategySubagent(_gateway()).execute(_ctx({}))
    assert out["house_view"]


async def test_asset_allocation_consumes_house_view() -> None:
    out = await AssetAllocationSubagent(_gateway()).execute(
        _ctx({"macro-strategy": {"house_view": "reflation"}})
    )
    assert out["tilts"]
    assert out["house_view"] == "reflation"


# --- buyside-research (parallel fan-out) -----------------------------------


async def test_buyside_research_returns_recommendation() -> None:
    out = await BuysideResearchSubagent("n1", _gateway()).execute(_ctx({}))
    assert out["name"] == "n1"
    assert "conviction" in out
    assert out["recommendation"] in {"buy", "hold", "sell"}


# --- portfolio-construction (join) -----------------------------------------


async def test_portfolio_construction_sums_target_notional() -> None:
    connectors = _connectors(**{"target:n1": "50", "target:n2": "50"})
    out = await PortfolioConstructionSubagent("pf1", ["n1", "n2"], _gateway(), connectors).execute(
        _ctx(
            {
                "asset-allocation": {"tilts": {"equity": 0.6}},
                "research:n1": {"name": "n1", "recommendation": "buy"},
                "research:n2": {"name": "n2", "recommendation": "hold"},
            }
        )
    )
    assert out["target_notional"] == pytest.approx(100.0)
    assert out["portfolio_id"] == "pf1"


# --- mandate & risk gate (MANDATORY) ---------------------------------------


def _gate_ctx(notional: float = 100.0) -> StepContext:
    return _ctx({"portfolio-construction": {"target_notional": notional, "portfolio_id": "pf1"}})


async def test_gate_passes_within_limits_and_liquid() -> None:
    connectors = _connectors(**{"limit:pf1": "1000", "liquidity:pf1": "ok"})
    out = await MandateRiskGateSubagent("pf1", _gateway(), connectors).execute(_gate_ctx())
    assert out["decision"] == GATE_PASS


async def test_gate_denies_over_limit() -> None:
    connectors = _connectors(**{"limit:pf1": "50", "liquidity:pf1": "ok"})
    out = await MandateRiskGateSubagent("pf1", _gateway(), connectors).execute(_gate_ctx())
    assert out["decision"] == GATE_DENY


async def test_gate_denies_when_illiquid() -> None:
    connectors = _connectors(**{"limit:pf1": "1000", "liquidity:pf1": "stressed"})
    out = await MandateRiskGateSubagent("pf1", _gateway(), connectors).execute(_gate_ctx())
    assert out["decision"] == GATE_DENY


async def test_gate_fails_closed_when_no_data() -> None:
    out = await MandateRiskGateSubagent("ghost", _gateway(), _connectors()).execute(_gate_ctx())
    assert out["decision"] == GATE_DENY


# --- buyside-execution (consequential, gated) ------------------------------


def test_place_orders_tool_is_consequential() -> None:
    assert PlaceOrdersTool().consequential is True


def _exec_ctx(decision: str) -> StepContext:
    return _ctx(
        {
            "mandate-risk-gate": {
                "decision": decision,
                "target_notional": 100.0,
                "portfolio_id": "pf1",
            }
        }
    )


async def test_execution_holds_orders_when_gate_passes() -> None:
    guardrails = _guardrails()
    out = await BuysideExecutionSubagent("pf1", guardrails).execute(_exec_ctx(GATE_PASS))
    assert out["blocked"] is False
    assert out["placed"] is False  # default-deny
    assert out["approval_id"] is not None
    assert len(guardrails.pending()) == 1
    assert guardrails.pending()[0].tool_name == "aim_place_orders"


async def test_execution_blocked_when_gate_denies() -> None:
    guardrails = _guardrails()
    out = await BuysideExecutionSubagent("pf1", guardrails).execute(_exec_ctx(GATE_DENY))
    assert out["blocked"] is True
    assert out["placed"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []
