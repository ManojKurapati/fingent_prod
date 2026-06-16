"""Orchestrator-graph tests for Private Markets.

Asserts the hybrid shape (origination head -> parallel diligence fan-out ->
selected underwriting -> IC commitment), that exactly one underwriting subagent
runs per asset class, that the diligence workstreams overlap concurrently, and
that the standalone stewardship monitor is sequential.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.private_markets.orchestrator import (
    PrivateMarketsOrchestrator,
    StewardshipOrchestrator,
)
from app.agents.financial_services.private_markets.schemas import DealRequest, MonitorRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_DILIGENCE_PROMPTS = {"diligence financials", "diligence legal", "diligence market"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors() -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(data={"pm:leverage:d1": "4.0", "pm:moic:d1": "2.5"})
    )


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[PrivateMarketsOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = PrivateMarketsOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def _request(asset_class: str = "credit") -> DealRequest:
    return DealRequest(deal_id="d1", asset_class=asset_class, sponsor="acme")


def test_graph_is_hybrid_with_origination_diligence_underwriting_commitment() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request("credit"))
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["origination-pipeline"].depends_on == ()
    for ws in ("diligence:financials", "diligence:legal", "diligence:market"):
        assert by_name[ws].depends_on == ("origination-pipeline",)
    # the selected underwriting fans in from all three diligence workstreams
    assert set(by_name["credit-underwriting"].depends_on) == {
        "diligence:financials",
        "diligence:legal",
        "diligence:market",
    }
    # IC commitment (capital) is strictly downstream of underwriting
    assert by_name["ic-commitment"].depends_on == ("credit-underwriting",)


def test_exactly_one_underwriting_subagent_per_asset_class() -> None:
    orch, _ = _orchestrator()
    for asset_class, expected in (
        ("pe_vc", "pe-vc-underwriting"),
        ("credit", "credit-underwriting"),
        ("real_asset", "real-asset-underwriting"),
        ("fund_of_funds", "fund-of-funds"),
    ):
        names = {s.name for s in orch.build_graph(_request(asset_class)).steps}
        underwriters = names & {
            "pe-vc-underwriting",
            "credit-underwriting",
            "real-asset-underwriting",
            "fund-of-funds",
        }
        assert underwriters == {expected}


async def test_diligence_workstreams_run_concurrently() -> None:
    """The three diligence workstreams must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_DILIGENCE_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _DILIGENCE_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request("credit")), timeout=1.0)
    assert result.outputs["ic-commitment"]["approval_id"] is not None


async def test_invest_deal_holds_capital_for_ic_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request("credit"))
    assert result.outputs["credit-underwriting"]["recommendation"] == "invest"
    # exactly one held capital commitment — the mandatory human IC gate
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "pm_commit_capital"
    assert result.outputs["ic-commitment"]["committed"] is False


async def test_declined_deal_commits_no_capital() -> None:
    connectors = build_fake_connector(store=FakeStore(data={"pm:leverage:d1": "9.0"}))
    orch, guardrails = _orchestrator(connectors=connectors)
    result = await orch.run(_request("credit"))
    assert result.outputs["credit-underwriting"]["recommendation"] == "pass"
    assert guardrails.pending() == []
    assert result.outputs["ic-commitment"]["committed"] is False


async def test_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request("credit"))
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["origination-pipeline"] < pos["diligence:financials"]
    assert pos["diligence:financials"] < pos["credit-underwriting"]
    assert pos["credit-underwriting"] < pos["ic-commitment"]
    assert result.order[-1] == "ic-commitment"


# --- standalone stewardship monitor (sequential) --------------------------


def test_stewardship_graph_is_sequential() -> None:
    orch = StewardshipOrchestrator(gateway=ClaudeGateway(transport=_stub), connectors=_connectors())
    graph = orch.build_graph(MonitorRequest(portfolio_id="p1"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["portfolio-stewardship"]


async def test_stewardship_run_reports_alerts() -> None:
    connectors = build_fake_connector(store=FakeStore(data={"pm:covenant_headroom:p1": "-0.2"}))
    orch = StewardshipOrchestrator(gateway=ClaudeGateway(transport=_stub), connectors=connectors)
    result = await orch.run(MonitorRequest(portfolio_id="p1"))
    assert "covenant" in result.outputs["portfolio-stewardship"]["alerts"]
