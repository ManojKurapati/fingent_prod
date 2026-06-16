"""Subagent-level tests for Tax — mocked Claude gateway + fake connectors.

Tax-type computations are deterministic off connector inputs; the provision
fan-in assembles them into current/deferred tax + ETR. Filing a return externally
is a **consequential** action routed through the guardrail engine (default-deny).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.tax.subagents import (
    AuditDefenceSubagent,
    DirectTaxComplianceSubagent,
    FileReturnTool,
    IndirectTaxSubagent,
    InternationalTaxSubagent,
    TaxFilingSubagent,
    TaxProvisionSubagent,
    TransferPricingSubagent,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text=f"[{model}] ok", input_tokens=3, output_tokens=2)


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


# --- tools ----------------------------------------------------------------


async def test_file_return_tool_is_consequential() -> None:
    assert FileReturnTool().consequential is True


# --- parallel compliance computations -------------------------------------


async def test_direct_tax_computes_current_tax_and_income() -> None:
    connectors = _connectors(
        **{"income:US": "1000", "rate:US": "0.21", "income:UK": "500", "rate:UK": "0.25"}
    )
    out = await DirectTaxComplianceSubagent(["US", "UK"], _gateway(), connectors).execute(_ctx({}))
    assert out["current_tax"] == {"US": 210.0, "UK": 125.0}
    assert out["total_current"] == pytest.approx(335.0)
    assert out["total_income"] == pytest.approx(1500.0)


async def test_indirect_tax_nets_output_against_input() -> None:
    connectors = _connectors(**{"vat_out:US": "300", "vat_in:US": "120"})
    out = await IndirectTaxSubagent(["US"], _gateway(), connectors).execute(_ctx({}))
    assert out["net_vat"] == {"US": 180.0}
    assert out["total"] == pytest.approx(180.0)


async def test_transfer_pricing_totals_adjustments() -> None:
    connectors = _connectors(**{"intercompany:US": "40", "intercompany:UK": "10"})
    out = await TransferPricingSubagent(["US", "UK"], _gateway(), connectors).execute(_ctx({}))
    assert out["adjustments"] == {"US": 40.0, "UK": 10.0}
    assert out["total"] == pytest.approx(50.0)


async def test_international_tax_totals_foreign_credits() -> None:
    connectors = _connectors(**{"foreign_tax:UK": "30"})
    out = await InternationalTaxSubagent(["UK"], _gateway(), connectors).execute(_ctx({}))
    assert out["foreign_credits"] == {"UK": 30.0}
    assert out["total"] == pytest.approx(30.0)


async def test_audit_defence_surfaces_open_disputes() -> None:
    connectors = _connectors(**{"dispute:US": "1", "dispute:UK": "0"})
    out = await AuditDefenceSubagent(["US", "UK"], _gateway(), connectors).execute(_ctx({}))
    assert out["open_disputes"] == ["US"]


# --- provision fan-in -----------------------------------------------------


async def test_provision_assembles_current_deferred_and_etr() -> None:
    results = {
        "direct-tax-compliance": {"total_current": 335.0, "total_income": 1500.0},
        "indirect-tax": {"total": 180.0},
        "transfer-pricing": {"total": 50.0},
        "international-tax": {"total": 30.0},
    }
    out = await TaxProvisionSubagent(_gateway()).execute(_ctx(results))
    assert out["current"] == pytest.approx(335.0)
    # deferred derived from TP + intl adjustments
    assert out["deferred"] == pytest.approx(80.0)
    assert out["total_tax"] == pytest.approx(415.0)
    assert out["etr"] == pytest.approx(415.0 / 1500.0)
    assert "disclosures" in out


async def test_provision_handles_zero_income_without_dividing() -> None:
    results = {
        "direct-tax-compliance": {"total_current": 0.0, "total_income": 0.0},
        "transfer-pricing": {"total": 0.0},
        "international-tax": {"total": 0.0},
    }
    out = await TaxProvisionSubagent(_gateway()).execute(_ctx(results))
    assert out["etr"] == pytest.approx(0.0)


# --- filing (consequential external action) -------------------------------


async def test_filing_holds_external_submission_default_deny() -> None:
    guardrails = _guardrails()
    out = await TaxFilingSubagent("ret-US-2026", "US", _gateway(), guardrails).execute(_ctx({}))
    assert out["return_id"] == "ret-US-2026"
    assert out["jurisdiction"] == "US"
    assert out["filed"] is False  # default-deny: held, not executed
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "tax_file_return"
