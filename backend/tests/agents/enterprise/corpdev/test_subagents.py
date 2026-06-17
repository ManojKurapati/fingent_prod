"""Subagent-level tests for Corporate Development & Strategy."""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.core import ClaudeGateway, RawCompletion, StepContext, StepEvent
from app.agents.enterprise.corpdev.subagents import (
    DealMaterialsSubagent,
    DueDiligenceSubagent,
    InvestorRelationsSubagent,
    PipelineSourcingSubagent,
    PublishDealRecommendationTool,
    PublishEarningsTool,
    StrategyAnalysisSubagent,
    ValuationModellingSubagent,
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


# --- pipeline-sourcing -----------------------------------------------------


async def test_pipeline_sourcing_ranks_targets_by_revenue() -> None:
    gw = _gateway()
    connectors = _connectors(**{"target:revenue:alpha": "50", "target:revenue:beta": "120"})
    out = await PipelineSourcingSubagent(["alpha", "beta"], gw, connectors).execute(_ctx({}))
    assert out["top_target"] == "beta"
    assert out["ranked"] == ["beta", "alpha"]
    assert gw.usage.calls >= 1


async def test_pipeline_sourcing_breaks_ties_deterministically() -> None:
    connectors = _connectors(**{"target:revenue:zeta": "10", "target:revenue:alpha": "10"})
    out = await PipelineSourcingSubagent(["zeta", "alpha"], _gateway(), connectors).execute(
        _ctx({})
    )
    # equal revenue -> alphabetical tie-break
    assert out["ranked"] == ["alpha", "zeta"]
    assert out["top_target"] == "alpha"


# --- valuation-modelling ---------------------------------------------------


async def test_valuation_models_ev_and_accretion() -> None:
    connectors = _connectors(**{"target:ebitda:beta": "10"})
    out = await ValuationModellingSubagent(8.0, 0.1, _gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["target"] == "beta"
    assert out["ev"] == pytest.approx(80.0)
    assert out["synergies"] == pytest.approx(1.0)
    assert out["accretive"] is True


async def test_valuation_not_accretive_without_synergies() -> None:
    connectors = _connectors(**{"target:ebitda:beta": "10"})
    out = await ValuationModellingSubagent(8.0, 0.0, _gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["accretive"] is False


async def test_valuation_models_real_eps_accretion_when_acquirer_connected() -> None:
    # Acquirer EPS = 100/100 = 1.00. EV = 10*8 = 80 -> 80/20 = 4 new shares.
    # Pro-forma NI = 100 + 5 (target) + 1 (synergies) = 106 over 104 shares = 1.0192.
    connectors = _connectors(
        **{
            "target:ebitda:beta": "10",
            "target:net_income:beta": "5",
            "acquirer:net_income": "100",
            "acquirer:shares": "100",
            "acquirer:share_price": "20",
        }
    )
    out = await ValuationModellingSubagent(8.0, 0.1, _gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["modelled"] is True
    assert out["acquirer_eps"] == pytest.approx(1.0)
    assert out["proforma_eps"] == pytest.approx(106.0 / 104.0, rel=1e-3)
    assert out["accretion_pct"] > 0
    assert out["accretive"] is True


async def test_valuation_flags_dilution_on_thin_target() -> None:
    # Big EV / lots of new shares, tiny target earnings -> EPS falls.
    connectors = _connectors(
        **{
            "target:ebitda:beta": "10",
            "target:net_income:beta": "1",
            "acquirer:net_income": "100",
            "acquirer:shares": "100",
            "acquirer:share_price": "1",  # EV 80 / 1 = 80 new shares
        }
    )
    out = await ValuationModellingSubagent(8.0, 0.0, _gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["modelled"] is True
    assert out["accretion_pct"] < 0
    assert out["accretive"] is False


# --- due-diligence ---------------------------------------------------------


async def test_due_diligence_clears_when_no_red_flags() -> None:
    connectors = _connectors(**{"target:redflags:beta": "0"})
    out = await DueDiligenceSubagent(_gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["red_flags"] == 0
    assert out["cleared"] is True


async def test_due_diligence_flags_block_clearance() -> None:
    connectors = _connectors(**{"target:redflags:beta": "2"})
    out = await DueDiligenceSubagent(_gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["red_flags"] == 2
    assert out["cleared"] is False
    # legacy aggregate key folds into the financial workstream
    assert out["by_workstream"]["financial"] == 2
    assert out["open_workstreams"] == ["financial"]


async def test_due_diligence_aggregates_across_workstreams() -> None:
    connectors = _connectors(
        **{
            "target:redflags:legal:beta": "1",
            "target:redflags:tax:beta": "3",
        }
    )
    out = await DueDiligenceSubagent(_gateway(), connectors).execute(
        _ctx({"pipeline-sourcing": {"top_target": "beta"}})
    )
    assert out["red_flags"] == 4
    assert out["cleared"] is False
    assert out["by_workstream"] == {
        "financial": 0,
        "legal": 1,
        "commercial": 0,
        "tax": 3,
        "operational": 0,
    }
    assert out["open_workstreams"] == ["legal", "tax"]


# --- deal-materials (consequential publish) --------------------------------


async def test_deal_materials_recommends_proceed_and_holds_publish() -> None:
    guardrails = _guardrails()
    out = await DealMaterialsSubagent(guardrails, _gateway()).execute(
        _ctx(
            {
                "valuation-modelling": {"target": "beta", "ev": 80.0, "accretive": True},
                "due-diligence": {"cleared": True, "red_flags": 0},
            }
        )
    )
    assert out["recommendation"] == "proceed"
    assert out["memo"]["target"] == "beta"
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "corpdev_publish_deal"
    assert pending[0].approver_role == "board"


async def test_deal_materials_holds_when_not_clear_or_dilutive() -> None:
    guardrails = _guardrails()
    out = await DealMaterialsSubagent(guardrails, _gateway()).execute(
        _ctx(
            {
                "valuation-modelling": {"target": "beta", "ev": 80.0, "accretive": False},
                "due-diligence": {"cleared": True, "red_flags": 0},
            }
        )
    )
    assert out["recommendation"] == "hold"
    # publication is still default-deny gated regardless of recommendation
    assert len(guardrails.pending()) == 1


async def test_deal_materials_assembles_cim_with_sections() -> None:
    out = await DealMaterialsSubagent(_guardrails(), _gateway()).execute(
        _ctx(
            {
                "valuation-modelling": {
                    "target": "beta",
                    "ev": 80.0,
                    "ebitda": 10.0,
                    "synergies": 1.0,
                    "proforma_eps": 1.02,
                    "accretion_pct": 0.02,
                    "accretive": True,
                },
                "due-diligence": {
                    "cleared": True,
                    "red_flags": 0,
                    "open_workstreams": [],
                },
            }
        )
    )
    cim = out["cim"]
    assert cim["target"] == "beta"
    assert cim["sections"] == [
        "executive-summary",
        "target-overview",
        "financials",
        "valuation",
        "synergies",
        "diligence-findings",
        "recommendation",
    ]
    assert cim["valuation"]["proforma_eps"] == 1.02
    assert cim["recommendation"] == "proceed"


async def test_publish_deal_tool_is_consequential() -> None:
    assert PublishDealRecommendationTool().consequential is True


# --- strategy-analysis -----------------------------------------------------


async def test_strategy_analysis_sums_tam_by_segment() -> None:
    connectors = _connectors(**{"market:saas": "300", "market:fintech": "200"})
    out = await StrategyAnalysisSubagent(["saas", "fintech"], _gateway(), connectors).execute(
        _ctx({})
    )
    assert out["tam"] == pytest.approx(500.0)
    assert out["by_segment"] == {"saas": 300.0, "fintech": 200.0}


# --- investor-relations (consequential publish) ----------------------------


async def test_investor_relations_holds_publish_and_flags_beat() -> None:
    guardrails = _guardrails()
    connectors = _connectors(**{"ir:consensus": "100", "ir:actual": "110"})
    out = await InvestorRelationsSubagent("Q1FY26", guardrails, _gateway(), connectors).execute(
        _ctx({})
    )
    assert out["pack"]["beat"] is True
    assert out["published"] is False
    assert out["approval_id"] is not None
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "corpdev_publish_earnings"


async def test_publish_earnings_tool_is_consequential() -> None:
    assert PublishEarningsTool().consequential is True
