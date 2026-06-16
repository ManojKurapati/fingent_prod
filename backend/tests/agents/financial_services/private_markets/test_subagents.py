"""Subagent-level tests for Private Markets — mocked gateway + fake connectors.

Covers the origination head, the parallel diligence workstreams, each asset-class
underwriting subagent's invest/pass rule, the default-deny IC commitment gate, and
the standalone stewardship monitor.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.financial_services.private_markets.subagents import (
    CommitCapitalTool,
    CreditUnderwritingSubagent,
    DiligenceSubagent,
    FundOfFundsSubagent,
    IcCommitmentSubagent,
    OriginationPipelineSubagent,
    PeVcUnderwritingSubagent,
    PortfolioStewardshipSubagent,
    RealAssetUnderwritingSubagent,
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


# --- origination ----------------------------------------------------------


async def test_origination_qualifies_deal() -> None:
    out = await OriginationPipelineSubagent("d1", "credit", _gateway()).execute(_ctx({}))
    assert out["qualified"] is True
    assert out["deal_id"] == "d1"
    assert out["asset_class"] == "credit"


# --- diligence fan-out ----------------------------------------------------


async def test_diligence_workstream_reports() -> None:
    connectors = _connectors(**{"pm:ebitda:d1": "50"})
    out = await DiligenceSubagent("financials", "d1", _gateway(), connectors).execute(
        _ctx({"origination-pipeline": {"qualified": True}})
    )
    assert out["workstream"] == "financials"
    assert out["ok"] is True


# --- underwriting (invest / pass rules) -----------------------------------


def _diligence_done() -> dict[str, Any]:
    return {
        "origination-pipeline": {"qualified": True, "deal_id": "d1"},
        "diligence:financials": {"ok": True},
        "diligence:legal": {"ok": True},
        "diligence:market": {"ok": True},
    }


async def test_credit_underwriting_invests_when_leverage_acceptable() -> None:
    connectors = _connectors(**{"pm:leverage:d1": "4.0"})
    out = await CreditUnderwritingSubagent("d1", _gateway(), connectors).execute(
        _ctx(_diligence_done())
    )
    assert out["recommendation"] == "invest"
    assert "ic_memo" in out


async def test_credit_underwriting_passes_when_leverage_too_high() -> None:
    connectors = _connectors(**{"pm:leverage:d1": "7.5"})
    out = await CreditUnderwritingSubagent("d1", _gateway(), connectors).execute(
        _ctx(_diligence_done())
    )
    assert out["recommendation"] == "pass"


async def test_pe_vc_underwriting_invests_on_strong_moic() -> None:
    connectors = _connectors(**{"pm:moic:d1": "2.5"})
    out = await PeVcUnderwritingSubagent("d1", _gateway(), connectors).execute(
        _ctx(_diligence_done())
    )
    assert out["recommendation"] == "invest"


async def test_real_asset_underwriting_passes_on_weak_irr() -> None:
    connectors = _connectors(**{"pm:irr:d1": "0.05"})
    out = await RealAssetUnderwritingSubagent("d1", _gateway(), connectors).execute(
        _ctx(_diligence_done())
    )
    assert out["recommendation"] == "pass"


async def test_fund_of_funds_invests_on_strong_track_record() -> None:
    connectors = _connectors(**{"pm:track:d1": "0.9"})
    out = await FundOfFundsSubagent("d1", _gateway(), connectors).execute(_ctx(_diligence_done()))
    assert out["recommendation"] == "invest"


# --- IC commitment gate (consequential, default-deny) ---------------------


async def test_commit_capital_tool_is_consequential() -> None:
    assert CommitCapitalTool().consequential is True


async def test_ic_commitment_holds_capital_until_ic_approves() -> None:
    guardrails = _guardrails()
    out = await IcCommitmentSubagent("d1", guardrails).execute(
        _ctx({"credit-underwriting": {"recommendation": "invest", "deal_id": "d1"}})
    )
    # default-deny: capital is NOT committed without the human IC vote
    assert out["committed"] is False
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "pm_commit_capital"


async def test_ic_commitment_skips_when_underwriting_recommends_pass() -> None:
    guardrails = _guardrails()
    out = await IcCommitmentSubagent("d1", guardrails).execute(
        _ctx({"credit-underwriting": {"recommendation": "pass", "deal_id": "d1"}})
    )
    assert out["committed"] is False
    assert out["approval_id"] is None
    # no capital commitment is even proposed for a declined deal
    assert guardrails.pending() == []


# --- stewardship ----------------------------------------------------------


async def test_stewardship_flags_covenant_breach() -> None:
    connectors = _connectors(**{"pm:covenant_headroom:p1": "-0.1"})
    out = await PortfolioStewardshipSubagent("p1", _gateway(), connectors).execute(_ctx({}))
    assert out["monitored"] is True
    assert "covenant" in out["alerts"]


async def test_stewardship_clean_when_within_covenants() -> None:
    connectors = _connectors(**{"pm:covenant_headroom:p1": "0.3"})
    out = await PortfolioStewardshipSubagent("p1", _gateway(), connectors).execute(_ctx({}))
    assert out["alerts"] == []
