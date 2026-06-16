"""Subagent-level tests for Accounting & Controllership.

Each subagent is exercised in isolation with a hand-built :class:`StepContext`
carrying its declared dependencies' outputs. Numeric inputs come from a fake
connector store; the Claude gateway is mocked. The only consequential action —
posting journal entries to the GL — is routed through the guardrail engine
(default-deny).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.accounting.subagents import (
    CloseOrchestrationSubagent,
    ConsolidationsSubagent,
    CostInventorySubagent,
    FixedAssetsSubagent,
    JournalEntriesSubagent,
    PostJournalEntryTool,
    ReconciliationsSubagent,
    TechnicalAccountingSubagent,
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


# --- close-orchestration --------------------------------------------------


async def test_close_orchestration_opens_period() -> None:
    gw = _gateway()
    out = await CloseOrchestrationSubagent("FY26-M06", ["e1", "e2"], gw).execute(_ctx({}))
    assert out["opened"] is True
    assert out["period"] == "FY26-M06"
    assert out["entities"] == ["e1", "e2"]
    assert gw.usage.calls >= 1


# --- journal-entries (consequential ledger post, default-deny) ------------


async def test_journal_entries_gates_ledger_post_default_deny() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"accrual:e1": "300", "accrual:e2": "200"})
    out = await JournalEntriesSubagent(["e1", "e2"], _gateway(), connectors, guardrails).execute(
        _ctx({"close-orchestration": {"opened": True}})
    )
    assert out["total"] == pytest.approx(500.0)
    assert out["posted"] is False  # default-deny: never posts without approval
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "accounting_post_journal_entry"


async def test_post_journal_entry_tool_is_consequential() -> None:
    assert PostJournalEntryTool().consequential is True


# --- fixed-assets ----------------------------------------------------------


async def test_fixed_assets_computes_straight_line_depreciation() -> None:
    connectors = _connectors(**{"asset_cost:e1": "6000"})
    out = await FixedAssetsSubagent(["e1"], _gateway(), connectors).execute(
        _ctx({"close-orchestration": {"opened": True}})
    )
    # 6000 / 5-year life = 1200 depreciation
    assert out["depreciation"]["e1"] == pytest.approx(1200.0)
    assert out["total_depreciation"] == pytest.approx(1200.0)


# --- cost-inventory --------------------------------------------------------


async def test_cost_inventory_computes_variance() -> None:
    connectors = _connectors(**{"inventory:e1": "1100", "std_cost:e1": "1000"})
    out = await CostInventorySubagent(["e1"], _gateway(), connectors).execute(
        _ctx({"close-orchestration": {"opened": True}})
    )
    assert out["variance"]["e1"] == pytest.approx(100.0)
    assert out["total_variance"] == pytest.approx(100.0)


# --- technical-accounting --------------------------------------------------


async def test_technical_accounting_ratable_revenue_schedule() -> None:
    connectors = _connectors(**{"contract:e1": "1200"})
    out = await TechnicalAccountingSubagent(["e1"], _gateway(), connectors).execute(
        _ctx({"close-orchestration": {"opened": True}})
    )
    # 1200 ratable over 12 periods -> 100/period (ASC 606)
    assert out["revenue_schedule"]["e1"] == pytest.approx(100.0)
    assert "memo" in out


# --- reconciliations (fan-in: ties sub-ledgers to GL) ---------------------


def _subledger_results(je: float, dep: float, var: float) -> dict[str, Any]:
    return {
        "journal-entries": {"total": je},
        "fixed-assets": {"total_depreciation": dep},
        "cost-inventory": {"total_variance": var},
        "technical-accounting": {"revenue_schedule": {}},
    }


async def test_reconciliations_ties_out_when_gl_matches() -> None:
    connectors = _connectors(**{"gl_control": "1500"})
    out = await ReconciliationsSubagent(_gateway(), connectors).execute(
        _ctx(_subledger_results(je=500.0, dep=800.0, var=200.0))
    )
    assert out["subledger_total"] == pytest.approx(1500.0)
    assert out["tied"] is True
    assert out["exceptions"] == []


async def test_reconciliations_flags_exception_on_mismatch() -> None:
    connectors = _connectors(**{"gl_control": "1000"})
    out = await ReconciliationsSubagent(_gateway(), connectors).execute(
        _ctx(_subledger_results(je=500.0, dep=800.0, var=200.0))
    )
    assert out["tied"] is False
    assert out["difference"] == pytest.approx(500.0)
    assert out["exceptions"] == ["gl_control"]


# --- consolidations (sequenced last) --------------------------------------


async def test_consolidations_translates_and_eliminates_intercompany() -> None:
    connectors = _connectors(
        **{
            "entity_balance:e1": "1000",
            "fx_rate:e1": "1.0",
            "ic:e1": "100",
            "entity_balance:e2": "500",
            "fx_rate:e2": "2.0",
            "ic:e2": "0",
        }
    )
    out = await ConsolidationsSubagent(["e1", "e2"], _gateway(), connectors).execute(
        _ctx({"reconciliations": {"tied": True}})
    )
    # e1: 1000*1.0 - 100 = 900 ; e2: 500*2.0 - 0 = 1000 ; group = 1900
    assert out["by_entity"]["e1"] == pytest.approx(900.0)
    assert out["by_entity"]["e2"] == pytest.approx(1000.0)
    assert out["group_total"] == pytest.approx(1900.0)
