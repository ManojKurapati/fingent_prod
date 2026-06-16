"""Subagent-level tests for Product, Strategy & Client.

Product definition is sequential (discovery -> pricing); launch is blocked behind
a mandatory compliance/regulatory-filing gate; client activation is blocked behind
a KYC gate. Both launch and activation are **consequential** (default-deny).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.product_strategy_client.subagents import (
    ClientActivationTool,
    ClientOnboardingSubagent,
    ClientServicesSubagent,
    ComplianceFilingGateSubagent,
    LaunchSubagent,
    PricingSubagent,
    ProductLaunchTool,
    ProductManagementSubagent,
    SalesDistributionSubagent,
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


# --- product-management + pricing -----------------------------------------


async def test_product_management_runs_discovery() -> None:
    gw = _gateway()
    out = await ProductManagementSubagent("FX-Hedge", gw).execute(_ctx({}))
    assert out["initiative"] == "FX-Hedge"
    assert out["requirements_ready"] is True
    assert gw.usage.calls >= 1


async def test_pricing_marks_up_cost_by_margin() -> None:
    connectors = _connectors(**{"pricing:cost": "100", "pricing:margin": "0.25"})
    out = await PricingSubagent(_gateway(), connectors).execute(
        _ctx({"product-management": {"requirements_ready": True}})
    )
    assert out["cost"] == pytest.approx(100.0)
    assert out["price"] == pytest.approx(125.0)


# --- compliance/regulatory-filing gate ------------------------------------


async def test_filing_gate_passes_with_cleared_token() -> None:
    connectors = _connectors(**{"filing:FT-1": "cleared"})
    out = await ComplianceFilingGateSubagent("FX-Hedge", "FT-1", connectors).execute(_ctx({}))
    assert out["passed"] is True


async def test_filing_gate_denies_without_token() -> None:
    out = await ComplianceFilingGateSubagent("FX-Hedge", None, _connectors()).execute(_ctx({}))
    assert out["passed"] is False


# --- launch (consequential, filing-gated) ---------------------------------


async def test_launch_blocked_when_filing_gate_fails() -> None:
    guardrails = _guardrails()
    out = await LaunchSubagent("FX-Hedge", guardrails).execute(
        _ctx({"compliance-filing": {"initiative": "FX-Hedge", "passed": False}})
    )
    assert out["blocked"] is True
    assert out["executed"] is False
    assert guardrails.pending() == []  # an unfiled product is never even submitted


async def test_launch_submits_default_deny_when_filing_passes() -> None:
    guardrails = _guardrails()
    out = await LaunchSubagent("FX-Hedge", guardrails).execute(
        _ctx({"compliance-filing": {"initiative": "FX-Hedge", "passed": True}})
    )
    assert out["blocked"] is False
    assert out["executed"] is False
    assert out["approval_id"] is not None
    assert guardrails.pending()[0].tool_name == "product_launch"


async def test_product_launch_tool_is_consequential() -> None:
    assert ProductLaunchTool().consequential is True


# --- commercial loop (parallel) -------------------------------------------


async def test_sales_distribution_builds_pipeline() -> None:
    out = await SalesDistributionSubagent(_gateway()).execute(_ctx({}))
    assert out["workstream"] == "sales-distribution"


async def test_client_services_scores_health() -> None:
    out = await ClientServicesSubagent(_gateway()).execute(_ctx({}))
    assert out["workstream"] == "client-services"


async def test_client_onboarding_blocked_without_kyc() -> None:
    guardrails = _guardrails()
    out = await ClientOnboardingSubagent("C1", None, guardrails, _connectors(), _gateway()).execute(
        _ctx({})
    )
    assert out["blocked"] is True
    assert out["executed"] is False
    assert guardrails.pending() == []


async def test_client_onboarding_submits_default_deny_when_kyc_cleared() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"kyc:KT-1": "cleared"})
    out = await ClientOnboardingSubagent("C1", "KT-1", guardrails, connectors, _gateway()).execute(
        _ctx({})
    )
    assert out["blocked"] is False
    assert out["executed"] is False
    assert out["approval_id"] is not None
    assert guardrails.pending()[0].tool_name == "product_activate_client"


async def test_client_activation_tool_is_consequential() -> None:
    assert ClientActivationTool().consequential is True
