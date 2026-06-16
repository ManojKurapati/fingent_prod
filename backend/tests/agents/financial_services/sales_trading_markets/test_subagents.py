"""Subagent-level tests for Sales & Trading / Markets.

The canonical financial-services dependency is exercised here: an order is routed
only after the **pre-trade risk gate** (limits / inventory / suitability) clears.
Routing an order is a **consequential** action — blocked outright on a gate deny
and otherwise held (default-deny) for trader/risk approval.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.sales_trading_markets.subagents import (
    GATE_DENY,
    GATE_PASS,
    ExecutionAlgoSubagent,
    PreTradeRiskGateSubagent,
    PricingQuotingSubagent,
    QuantSignalsSubagent,
    RiskHedgingSubagent,
    RouteOrderTool,
    SalesCoverageSubagent,
    StructuringSubagent,
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


# --- parallel feeds --------------------------------------------------------


async def test_sales_coverage_reports_flow() -> None:
    out = await SalesCoverageSubagent("acct1", _gateway()).execute(_ctx({}))
    assert out["account"] == "acct1"
    assert "wallet_share" in out


async def test_pricing_quoting_reads_price_and_quotes_two_way() -> None:
    connectors = _connectors(**{"price:AAPL": "10"})
    out = await PricingQuotingSubagent("AAPL", _gateway(), connectors).execute(_ctx({}))
    assert out["price"] == pytest.approx(10.0)
    assert out["bid"] < out["ask"]  # two-way market


async def test_quant_signals_emits_a_signal() -> None:
    out = await QuantSignalsSubagent("AAPL", _gateway()).execute(_ctx({}))
    assert "signal" in out


async def test_structuring_decomposes_into_components() -> None:
    out = await StructuringSubagent("AAPL", _gateway()).execute(_ctx({}))
    assert out["components"]


# --- pre-trade risk gate (MANDATORY) ---------------------------------------


def _gate_ctx(price: float = 10.0) -> StepContext:
    return _ctx({"pricing-quoting": {"price": price}})


async def test_risk_gate_passes_within_limits_and_suitable() -> None:
    connectors = _connectors(
        **{"limit:eqbook": "1000", "exposure:eqbook": "100", "suitable:acct1": "yes"}
    )
    out = await PreTradeRiskGateSubagent("acct1", "eqbook", 5.0, _gateway(), connectors).execute(
        _gate_ctx()
    )
    assert out["decision"] == GATE_PASS
    assert out["notional"] == pytest.approx(50.0)


async def test_risk_gate_denies_when_over_limit() -> None:
    connectors = _connectors(
        **{"limit:eqbook": "120", "exposure:eqbook": "100", "suitable:acct1": "yes"}
    )
    out = await PreTradeRiskGateSubagent("acct1", "eqbook", 5.0, _gateway(), connectors).execute(
        _gate_ctx()
    )
    assert out["decision"] == GATE_DENY


async def test_risk_gate_denies_when_unsuitable() -> None:
    connectors = _connectors(
        **{"limit:eqbook": "1000", "exposure:eqbook": "100", "suitable:acct1": "no"}
    )
    out = await PreTradeRiskGateSubagent("acct1", "eqbook", 5.0, _gateway(), connectors).execute(
        _gate_ctx()
    )
    assert out["decision"] == GATE_DENY


async def test_risk_gate_fails_closed_when_no_limit_data() -> None:
    out = await PreTradeRiskGateSubagent("acct1", "ghost", 5.0, _gateway(), _connectors()).execute(
        _gate_ctx()
    )
    assert out["decision"] == GATE_DENY


# --- execution-algo (consequential, gated) ---------------------------------


def test_route_order_tool_is_consequential() -> None:
    assert RouteOrderTool().consequential is True


def _exec_ctx(decision: str) -> StepContext:
    return _ctx({"pre-trade-risk-gate": {"decision": decision, "notional": 50.0, "book": "eqbook"}})


async def test_execution_holds_route_order_when_gate_passes() -> None:
    guardrails = _guardrails()
    out = await ExecutionAlgoSubagent("o1", guardrails).execute(_exec_ctx(GATE_PASS))
    assert out["blocked"] is False
    assert out["routed"] is False  # default-deny: held until approved
    assert out["approval_id"] is not None
    assert len(guardrails.pending()) == 1
    assert guardrails.pending()[0].tool_name == "markets_route_order"


async def test_execution_blocked_when_gate_denies() -> None:
    guardrails = _guardrails()
    out = await ExecutionAlgoSubagent("o1", guardrails).execute(_exec_ctx(GATE_DENY))
    assert out["blocked"] is True
    assert out["routed"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []  # nothing reaches the queue on a deny


# --- risk-hedging (post-fill) ----------------------------------------------


async def test_risk_hedging_reports_post_fill_state() -> None:
    out = await RiskHedgingSubagent("eqbook", _gateway()).execute(
        _ctx({"execution-algo": {"blocked": False, "routed": False}})
    )
    assert out["book"] == "eqbook"
    assert "rehedged" in out
