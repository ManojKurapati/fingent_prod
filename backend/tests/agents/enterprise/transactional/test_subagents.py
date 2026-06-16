"""Subagent-level tests for Transactional / Operational Finance.

Each subagent is exercised in isolation with a hand-built :class:`StepContext`
carrying its declared dependencies' outputs. Numeric inputs come from a fake
connector; the Claude gateway is mocked. Cash-movement actions (AP payment runs,
payroll disbursement) are routed through the guardrail engine (default-deny).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.transactional.subagents import (
    AccountsPayableSubagent,
    AccountsReceivableSubagent,
    BillingSubagent,
    CollectionsSubagent,
    ExecutePaymentTool,
    InvoiceMatchSubagent,
    PayrollSubagent,
    ProcurementSubagent,
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


async def test_execute_payment_tool_is_consequential() -> None:
    assert ExecutePaymentTool().consequential is True


# --- accounts-payable (consequential cash movement) -----------------------


async def test_ap_matches_invoices_and_holds_payment_default_deny() -> None:
    guardrails = _guardrails()
    connectors = _connectors(
        **{"invoice:v1": "500", "po:v1": "500", "invoice:v2": "200", "po:v2": "999"}
    )
    out = await AccountsPayableSubagent(["v1", "v2"], _gateway(), connectors, guardrails).execute(
        _ctx({})
    )
    assert out["matched"] == {"v1": 500.0}  # v2 fails 3-way match
    assert out["exceptions"] == ["v2"]
    assert out["total"] == pytest.approx(500.0)
    assert out["approval_id"] is not None
    # default-deny: the disbursement is held, not executed
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "transactional_execute_payment"


async def test_ap_with_no_matches_proposes_no_payment() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"invoice:v1": "500", "po:v1": "10"})
    out = await AccountsPayableSubagent(["v1"], _gateway(), connectors, guardrails).execute(
        _ctx({})
    )
    assert out["matched"] == {}
    assert out["exceptions"] == ["v1"]
    assert out["approval_id"] is None
    assert guardrails.pending() == []


# --- payroll (consequential cash movement) --------------------------------


async def test_payroll_totals_gross_and_holds_disbursement() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"payroll:e1": "1000", "payroll:e2": "1500"})
    out = await PayrollSubagent(["e1", "e2"], _gateway(), connectors, guardrails).execute(_ctx({}))
    assert out["gross"] == {"e1": 1000.0, "e2": 1500.0}
    assert out["total"] == pytest.approx(2500.0)
    assert out["approval_id"] is not None
    assert len(guardrails.pending()) == 1


async def test_payroll_with_no_employees_holds_nothing() -> None:
    guardrails = _guardrails()
    out = await PayrollSubagent([], _gateway(), _connectors(), guardrails).execute(_ctx({}))
    assert out["total"] == pytest.approx(0.0)
    assert out["approval_id"] is None
    assert guardrails.pending() == []


# --- procurement ----------------------------------------------------------


async def test_procurement_tracks_spend_vs_budget() -> None:
    connectors = _connectors(**{"spend:total": "120", "budget:total": "100"})
    out = await ProcurementSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["spend"] == pytest.approx(120.0)
    assert out["budget"] == pytest.approx(100.0)
    assert out["over_budget"] is True


# --- O2C lane: billing -> accounts-receivable -> collections --------------


async def test_billing_generates_invoices_from_contracts() -> None:
    connectors = _connectors(**{"contract:c1": "300", "contract:c2": "150"})
    out = await BillingSubagent(["c1", "c2"], _gateway(), connectors).execute(_ctx({}))
    assert out["invoices"] == {"c1": 300.0, "c2": 150.0}
    assert out["total_billed"] == pytest.approx(450.0)


async def test_ar_applies_cash_and_computes_open_items() -> None:
    connectors = _connectors(**{"cash:c1": "300", "cash:c2": "100"})
    out = await AccountsReceivableSubagent(["c1", "c2"], _gateway(), connectors).execute(
        _ctx({"billing": {"invoices": {"c1": 300.0, "c2": 150.0}}})
    )
    assert out["applied"] == {"c1": 300.0, "c2": 100.0}
    assert out["open_items"] == {"c1": 0.0, "c2": 50.0}


async def test_collections_flags_overdue_open_items() -> None:
    out = await CollectionsSubagent(_gateway()).execute(
        _ctx({"accounts-receivable": {"open_items": {"c1": 0.0, "c2": 50.0}}})
    )
    assert out["overdue"] == ["c2"]


# --- parallel AP payment-run: per-vendor invoice match --------------------


async def test_invoice_match_matched_holds_payment() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"invoice:v1": "500", "po:v1": "500"})
    out = await InvoiceMatchSubagent("v1", _gateway(), connectors, guardrails).execute(_ctx({}))
    assert out["vendor"] == "v1"
    assert out["matched"] is True
    assert out["amount"] == pytest.approx(500.0)
    assert out["approval_id"] is not None
    assert len(guardrails.pending()) == 1


async def test_invoice_match_mismatch_holds_nothing() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"invoice:v1": "500", "po:v1": "1"})
    out = await InvoiceMatchSubagent("v1", _gateway(), connectors, guardrails).execute(_ctx({}))
    assert out["matched"] is False
    assert out["approval_id"] is None
    assert guardrails.pending() == []
