"""Subagent-level tests for Quantitative, Data & Technology.

The six research workstreams produce candidate models/strategies (narrative via
the mocked gateway). Promotion to production is **consequential** and is blocked
unless an independent model-validation gate (a Risk-Agent validation token) clears.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.quantitative_data_technology.subagents import (
    DataScienceSubagent,
    FinancialEngineeringSubagent,
    ModelPromotionTool,
    ModelValidationGateSubagent,
    PromoteSubagent,
    QuantPricingSubagent,
    QuantResearchSubagent,
    RiskModelDevSubagent,
    SystematicDevSubagent,
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


@pytest.mark.parametrize(
    ("cls", "workstream"),
    [
        (QuantPricingSubagent, "quant-pricing"),
        (QuantResearchSubagent, "quant-research"),
        (RiskModelDevSubagent, "risk-model-dev"),
        (DataScienceSubagent, "data-science"),
        (FinancialEngineeringSubagent, "financial-engineering"),
        (SystematicDevSubagent, "systematic-dev"),
    ],
)
async def test_research_workstreams_emit_candidates(cls: Any, workstream: str) -> None:
    gw = _gateway()
    out = await cls(gw).execute(_ctx({}))
    assert out["workstream"] == workstream
    assert out["candidate"] is True
    assert gw.usage.calls >= 1


# --- model-validation gate ------------------------------------------------


async def test_validation_gate_passes_with_approved_token() -> None:
    connectors = _connectors(**{"validation:VT-1": "approved"})
    out = await ModelValidationGateSubagent("M1", "VT-1", connectors).execute(_ctx({}))
    assert out["passed"] is True
    assert out["model_id"] == "M1"


async def test_validation_gate_denies_without_token() -> None:
    out = await ModelValidationGateSubagent("M1", None, _connectors()).execute(_ctx({}))
    assert out["passed"] is False


async def test_validation_gate_denies_unapproved_token() -> None:
    connectors = _connectors(**{"validation:VT-9": "rejected"})
    out = await ModelValidationGateSubagent("M1", "VT-9", connectors).execute(_ctx({}))
    assert out["passed"] is False


# --- promote (consequential, gated) ---------------------------------------


async def test_promote_blocked_when_validation_failed_no_submission() -> None:
    guardrails = _guardrails()
    out = await PromoteSubagent("M1", guardrails).execute(
        _ctx({"model-validation": {"model_id": "M1", "passed": False}})
    )
    assert out["blocked"] is True
    assert out["executed"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []  # a failed gate is never even submitted


async def test_promote_submits_default_deny_when_validation_passed() -> None:
    guardrails = _guardrails()
    out = await PromoteSubagent("M1", guardrails).execute(
        _ctx({"model-validation": {"model_id": "M1", "passed": True}})
    )
    assert out["blocked"] is False
    assert out["executed"] is False  # default-deny: held for approval
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "quant_promote_model"


async def test_model_promotion_tool_is_consequential() -> None:
    assert ModelPromotionTool().consequential is True
