"""Subagent-level tests for the Insurance group-agent.

Numeric inputs come from fake connectors (deterministic maths); the Claude gateway
is mocked. Each subagent runs in isolation with a hand-built :class:`StepContext`.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.insurance.subagents import (
    ActuarialSubagent,
    BindPolicyTool,
    CatModellingSubagent,
    ClaimsSubagent,
    ProductSubagent,
    ReinsuranceSubagent,
    UnderwritingSubagent,
    accumulation_gate,
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


# --- actuarial ------------------------------------------------------------


async def test_actuarial_prices_premium_from_rate() -> None:
    connectors = _connectors(**{"rate:US-FL": "0.03"})
    out = await ActuarialSubagent("US-FL", 1_000_000.0, _gateway(), connectors).execute(_ctx({}))
    assert out["rate"] == pytest.approx(0.03)
    assert out["premium"] == pytest.approx(30_000.0)


async def test_actuarial_defaults_rate_when_absent() -> None:
    out = await ActuarialSubagent("US-FL", 1000.0, _gateway(), _connectors()).execute(_ctx({}))
    assert out["rate"] == pytest.approx(0.02)
    assert out["premium"] == pytest.approx(20.0)


# --- cat-modelling --------------------------------------------------------


async def test_cat_modelling_computes_pml_and_aal() -> None:
    connectors = _connectors(**{"catfactor:hurricane": "0.1"})
    out = await CatModellingSubagent("hurricane", 1_000_000.0, _gateway(), connectors).execute(
        _ctx({})
    )
    assert out["pml"] == pytest.approx(100_000.0)
    assert out["aal"] == pytest.approx(10_000.0)


# --- underwriting (join) --------------------------------------------------


def _uw_ctx(premium: float, pml: float) -> StepContext:
    return _ctx(
        {
            "actuarial": {"premium": premium, "rate": 0.02},
            "cat-modelling": {"pml": pml, "aal": pml * 0.1},
        }
    )


async def test_underwriting_accepts_within_appetite() -> None:
    connectors = _connectors(
        **{"accumulation:US-FL:hurricane": "100000", "limit:US-FL:hurricane": "500000"}
    )
    out = await UnderwritingSubagent("US-FL", "hurricane", _gateway(), connectors).execute(
        _uw_ctx(premium=30_000.0, pml=100_000.0)
    )
    assert out["within_appetite"] is True
    assert out["decision"] == "accept"
    assert out["proposed_accumulation"] == pytest.approx(200_000.0)


async def test_underwriting_declines_when_accumulation_breached() -> None:
    connectors = _connectors(
        **{"accumulation:US-FL:hurricane": "450000", "limit:US-FL:hurricane": "500000"}
    )
    out = await UnderwritingSubagent("US-FL", "hurricane", _gateway(), connectors).execute(
        _uw_ctx(premium=30_000.0, pml=100_000.0)
    )
    assert out["within_appetite"] is False
    assert out["decision"] == "decline"


# --- accumulation gate (mandatory pre-bind risk check) --------------------


async def test_accumulation_gate_passes_within_limit() -> None:
    connectors = _connectors(
        **{"accumulation:US-FL:hurricane": "100000", "limit:US-FL:hurricane": "500000"}
    )
    result = await accumulation_gate(connectors, "US-FL", "hurricane", 100_000.0)
    assert result.passed is True
    assert result.proposed == pytest.approx(200_000.0)


async def test_accumulation_gate_denies_over_limit() -> None:
    connectors = _connectors(
        **{"accumulation:US-FL:hurricane": "450000", "limit:US-FL:hurricane": "500000"}
    )
    result = await accumulation_gate(connectors, "US-FL", "hurricane", 100_000.0)
    assert result.passed is False


async def test_accumulation_gate_fail_closed_when_limit_absent() -> None:
    # No limit configured -> fail-closed DENY (never default-open).
    result = await accumulation_gate(_connectors(), "US-FL", "hurricane", 1.0)
    assert result.passed is False


# --- claims ---------------------------------------------------------------


async def test_claims_triages_and_reserves() -> None:
    out = await ClaimsSubagent("CLM1", 50_000.0, _gateway(), _connectors()).execute(_ctx({}))
    assert out["claim_id"] == "CLM1"
    assert out["reserve"] == pytest.approx(50_000.0)
    assert out["coverage_verified"] is True
    assert out["suspected_fraud"] is False


async def test_claims_flags_suspected_fraud() -> None:
    connectors = _connectors(**{"fraudflag:CLM9": "1"})
    out = await ClaimsSubagent("CLM9", 50_000.0, _gateway(), connectors).execute(_ctx({}))
    assert out["suspected_fraud"] is True


# --- reinsurance ----------------------------------------------------------


async def test_reinsurance_computes_ceded_above_retention() -> None:
    connectors = _connectors(**{"grossexposure:US-FL": "1000000", "retention:US-FL": "400000"})
    out = await ReinsuranceSubagent("US-FL", _gateway(), connectors).execute(_ctx({}))
    assert out["ceded"] == pytest.approx(600_000.0)
    assert out["retention"] == pytest.approx(400_000.0)


# --- product --------------------------------------------------------------


async def test_product_reports_combined_ratio() -> None:
    connectors = _connectors(**{"combinedratio:homeowners": "0.92"})
    out = await ProductSubagent("homeowners", _gateway(), connectors).execute(_ctx({}))
    assert out["combined_ratio"] == pytest.approx(0.92)
    assert out["profitable"] is True


# --- bind tool is consequential -------------------------------------------


def test_bind_policy_tool_is_consequential() -> None:
    assert BindPolicyTool().consequential is True
