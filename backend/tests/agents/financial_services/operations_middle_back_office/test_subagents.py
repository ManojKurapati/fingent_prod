"""Subagent-level tests for Operations (Middle & Back Office).

Each subagent runs in isolation with a mocked Claude gateway and fake connectors.
The settlement instruction is a **consequential** action: it must never execute
directly, and it is refused outright when the trade is not yet confirmed
(you cannot settle an unconfirmed trade).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.operations_middle_back_office.subagents import (
    CollateralMgmtSubagent,
    CustodyOpsSubagent,
    FundAccountingSubagent,
    ReconciliationsSubagent,
    SettlementInstructionTool,
    SettlementsSubagent,
    TradeSupportSubagent,
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


# --- trade-support --------------------------------------------------------


async def test_trade_support_confirms_when_counterparty_affirmed() -> None:
    gw = _gateway()
    connectors = _connectors(**{"trade:T1:affirmed": "yes"})
    out = await TradeSupportSubagent("T1", gw, connectors).execute(_ctx({}))
    assert out["trade_id"] == "T1"
    assert out["confirmed"] is True
    assert gw.usage.calls >= 1


async def test_trade_support_not_confirmed_when_unaffirmed() -> None:
    out = await TradeSupportSubagent("T2", _gateway(), _connectors()).execute(_ctx({}))
    assert out["confirmed"] is False


# --- settlements (consequential, sequential gate) -------------------------


async def test_settlements_blocks_unconfirmed_trade_without_gating() -> None:
    guardrails = _guardrails()
    out = await SettlementsSubagent("T2", 1_000.0, guardrails).execute(
        _ctx({"trade-support": {"trade_id": "T2", "confirmed": False}})
    )
    assert out["blocked"] is True
    assert out["executed"] is False
    assert out["approval_id"] is None
    # nothing was ever submitted — an unconfirmed trade is refused, not held
    assert guardrails.pending() == []


async def test_settlements_submits_confirmed_trade_default_deny() -> None:
    guardrails = _guardrails()
    out = await SettlementsSubagent("T1", 1_000.0, guardrails).execute(
        _ctx({"trade-support": {"trade_id": "T1", "confirmed": True}})
    )
    assert out["blocked"] is False
    assert out["requested"] is True
    assert out["executed"] is False  # default-deny: held for approval
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "ops_instruct_settlement"


async def test_settlement_instruction_tool_is_consequential() -> None:
    assert SettlementInstructionTool().consequential is True


# --- parallel reconciliation surfaces -------------------------------------


async def test_reconciliations_detects_break() -> None:
    connectors = _connectors(**{"recon:internal": "100", "recon:external": "90"})
    out = await ReconciliationsSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["break_amount"] == pytest.approx(10.0)
    assert out["has_break"] is True


async def test_fund_accounting_computes_nav() -> None:
    connectors = _connectors(
        **{"nav:assets": "1000", "nav:liabilities": "200", "nav:shares": "100"}
    )
    out = await FundAccountingSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["nav"] == pytest.approx(8.0)


async def test_custody_ops_reconciles_holdings() -> None:
    connectors = _connectors(**{"custody:holdings": "500", "custody:custodian": "500"})
    out = await CustodyOpsSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["reconciled"] is True


async def test_collateral_mgmt_computes_margin_call() -> None:
    connectors = _connectors(**{"collateral:exposure": "300", "collateral:posted": "120"})
    out = await CollateralMgmtSubagent(_gateway(), connectors).execute(_ctx({}))
    assert out["margin_call"] == pytest.approx(180.0)
