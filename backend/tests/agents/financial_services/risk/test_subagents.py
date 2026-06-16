"""Subagent-level tests for the Risk Management group-agent.

Each risk-type measure reads its metric + limit from fake connectors; the
aggregation join consolidates them and, on a breach, routes a limit-override to the
guardrail engine (default-deny). The synchronous pre-trade / limit-check gates are
exercised here too — they are the mandatory checks other agents call.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.risk.subagents import (
    CreditRiskSubagent,
    ErmAggregationSubagent,
    LiquidityRiskSubagent,
    MarketRiskSubagent,
    ModelValidationSubagent,
    OperationalRiskSubagent,
    RequestLimitOverrideTool,
    limit_check_gate,
    pre_trade_gate,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


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


# --- the four risk-type measures ------------------------------------------


async def test_market_risk_flags_var_breach() -> None:
    out = await MarketRiskSubagent(
        "trading", _gateway(), _connectors(**{"var:trading": "120", "varlimit:trading": "100"})
    ).execute(_ctx({}))
    assert out["var"] == pytest.approx(120.0)
    assert out["breach"] is True


async def test_market_risk_within_limit() -> None:
    out = await MarketRiskSubagent(
        "trading", _gateway(), _connectors(**{"var:trading": "80", "varlimit:trading": "100"})
    ).execute(_ctx({}))
    assert out["breach"] is False


async def test_credit_risk_computes_ecl_breach() -> None:
    out = await CreditRiskSubagent(
        "banking", _gateway(), _connectors(**{"ecl:banking": "60", "ecllimit:banking": "50"})
    ).execute(_ctx({}))
    assert out["ecl"] == pytest.approx(60.0)
    assert out["breach"] is True


async def test_operational_risk_within_limit() -> None:
    out = await OperationalRiskSubagent(
        "firm", _gateway(), _connectors(**{"oploss:firm": "10", "oplosslimit:firm": "50"})
    ).execute(_ctx({}))
    assert out["breach"] is False


async def test_liquidity_risk_breaches_below_floor() -> None:
    # LCR below its regulatory floor is a breach.
    out = await LiquidityRiskSubagent(
        "firm", _gateway(), _connectors(**{"lcr:firm": "0.9", "lcrmin:firm": "1.0"})
    ).execute(_ctx({}))
    assert out["breach"] is True


async def test_model_validation_independent_assurance() -> None:
    out = await ModelValidationSubagent(
        "firm", _gateway(), _connectors(**{"modeldrift:firm": "0.2", "driftlimit:firm": "0.1"})
    ).execute(_ctx({}))
    assert out["validated"] is False  # drift exceeds tolerance


# --- erm aggregation (barrier / join) -------------------------------------


def _all_clear() -> dict[str, Any]:
    return {
        "market-risk": {"breach": False},
        "credit-risk": {"breach": False},
        "operational-risk": {"breach": False},
        "liquidity-risk": {"breach": False},
        "model-validation": {"validated": True},
    }


async def test_erm_aggregation_no_breach_no_escalation() -> None:
    guardrails = _guardrails()
    out = await ErmAggregationSubagent(guardrails).execute(_ctx(_all_clear()))
    assert out["within_appetite"] is True
    assert out["escalated"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []


async def test_erm_aggregation_breach_escalates_via_guardrail_default_deny() -> None:
    guardrails = _guardrails()
    results = _all_clear()
    results["market-risk"] = {"breach": True}
    out = await ErmAggregationSubagent(guardrails).execute(_ctx(results))
    assert out["within_appetite"] is False
    assert out["escalated"] is True
    assert out["breaches"] == ["market-risk"]
    assert out["approval_id"] is not None
    # default-deny: the CRO limit-override is held, not executed
    assert len(guardrails.pending()) == 1
    assert guardrails.pending()[0].tool_name == "risk_request_limit_override"


async def test_erm_aggregation_flags_model_validation_failure() -> None:
    guardrails = _guardrails()
    results = _all_clear()
    results["model-validation"] = {"validated": False}
    out = await ErmAggregationSubagent(guardrails).execute(_ctx(results))
    assert out["within_appetite"] is False
    assert out["breaches"] == ["model-validation"]
    assert len(guardrails.pending()) == 1


async def test_limit_override_executes_only_after_cro_approval() -> None:
    guardrails = _guardrails()
    results = _all_clear()
    results["credit-risk"] = {"breach": True}
    out = await ErmAggregationSubagent(guardrails).execute(_ctx(results))
    # default-deny holds it; the CRO override fires only post-approval
    decision = await guardrails.approve(out["approval_id"], approver="cro-pat")
    assert decision.executed is True
    assert decision.output == "escalated:['credit-risk']"


def test_request_limit_override_tool_is_consequential() -> None:
    assert RequestLimitOverrideTool().consequential is True


# --- synchronous gates other agents call ----------------------------------


async def test_pre_trade_gate_passes_within_limit() -> None:
    decision = await pre_trade_gate(
        _connectors(**{"exposure:trading": "100", "limit:trading": "1000"}), "trading", 50.0
    )
    assert decision.decision == "PASS"
    assert decision.token is not None


async def test_pre_trade_gate_denies_over_limit() -> None:
    decision = await pre_trade_gate(
        _connectors(**{"exposure:trading": "990", "limit:trading": "1000"}), "trading", 50.0
    )
    assert decision.decision == "DENY"
    assert decision.token is None


async def test_pre_trade_gate_fail_closed_when_limit_absent() -> None:
    decision = await pre_trade_gate(_connectors(), "trading", 1.0)
    assert decision.decision == "DENY"


async def test_limit_check_gate_passes_within_limit() -> None:
    decision = await limit_check_gate(
        _connectors(**{"exposure:trading": "100", "limit:trading": "1000"}), "trading"
    )
    assert decision.decision == "PASS"


async def test_limit_check_gate_fail_closed_when_limit_absent() -> None:
    decision = await limit_check_gate(_connectors(), "trading")
    assert decision.decision == "DENY"
