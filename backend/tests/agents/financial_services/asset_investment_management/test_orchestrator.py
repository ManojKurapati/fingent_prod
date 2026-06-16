"""Orchestrator-graph tests for Asset & Investment Management.

Asserts the HYBRID rebalance graph (sequential macro->allocation spine ‖ parallel
research fan-out, joined at portfolio-construction, then a MANDATORY mandate/risk
gate before gated execution) and the standalone PARALLEL research orchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.asset_investment_management.orchestrator import (
    AimRebalanceOrchestrator,
    AimResearchOrchestrator,
)
from app.agents.financial_services.asset_investment_management.schemas import (
    RebalanceRequest,
    ResearchRequest,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(*, limit: str = "1000") -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(
            data={"target:n1": "50", "target:n2": "50", "limit:pf1": limit, "liquidity:pf1": "ok"}
        )
    )


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[AimRebalanceOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = AimRebalanceOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def _request() -> RebalanceRequest:
    return RebalanceRequest(portfolio_id="pf1", names=["n1", "n2"], period="FY26")


def test_graph_is_hybrid_with_spine_fanout_join_gate_execution() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["macro-strategy"].depends_on == ()
    assert by_name["asset-allocation"].depends_on == ("macro-strategy",)
    assert by_name["research:n1"].depends_on == ()
    assert by_name["research:n2"].depends_on == ()
    # construction joins the allocation spine and every research branch
    assert set(by_name["portfolio-construction"].depends_on) == {
        "asset-allocation",
        "research:n1",
        "research:n2",
    }
    assert by_name["mandate-risk-gate"].depends_on == ("portfolio-construction",)
    assert by_name["buyside-execution"].depends_on == ("mandate-risk-gate",)


async def test_research_fanout_runs_concurrently() -> None:
    """research:<name> branches must overlap (barrier deadlocks otherwise)."""
    names = [f"n{i}" for i in range(4)]
    barrier = asyncio.Barrier(len(names))
    research_prompts = {f"research {n}" for n in names}

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in research_prompts:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    store = FakeStore(
        data={**{f"target:{n}": "10" for n in names}, "limit:pf1": "1000", "liquidity:pf1": "ok"}
    )
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = AimRebalanceOrchestrator(
        gateway=ClaudeGateway(transport=gated),
        guardrails=guardrails,
        connectors=build_fake_connector(store=store),
    )
    result = await asyncio.wait_for(
        orch.run(RebalanceRequest(portfolio_id="pf1", names=names, period="FY26")), timeout=1.0
    )
    assert result.outputs["mandate-risk-gate"]["decision"] == "PASS"


async def test_clean_run_holds_orders_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())
    assert result.outputs["mandate-risk-gate"]["decision"] == "PASS"
    assert result.outputs["buyside-execution"]["blocked"] is False
    assert result.outputs["buyside-execution"]["placed"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "aim_place_orders"


async def test_over_limit_run_blocks_execution_before_the_gate() -> None:
    orch, guardrails = _orchestrator(connectors=_connectors(limit="50"))
    result = await orch.run(_request())
    assert result.outputs["mandate-risk-gate"]["decision"] == "DENY"
    assert result.outputs["buyside-execution"]["blocked"] is True
    assert guardrails.pending() == []


async def test_ordering_spine_join_gate_execution() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["macro-strategy"] < pos["asset-allocation"] < pos["portfolio-construction"]
    assert pos["research:n1"] < pos["portfolio-construction"]
    assert pos["portfolio-construction"] < pos["mandate-risk-gate"] < pos["buyside-execution"]


# --- standalone research path (parallel) -----------------------------------


def test_research_graph_is_parallel() -> None:
    orch = AimResearchOrchestrator(gateway=ClaudeGateway(transport=_stub))
    graph = orch.build_graph(ResearchRequest(names=["n1", "n2", "n3"]))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert {s.name for s in graph.steps} == {"research:n1", "research:n2", "research:n3"}
    assert all(s.depends_on == () for s in graph.steps)


async def test_research_run_produces_a_recommendation_per_name() -> None:
    orch = AimResearchOrchestrator(gateway=ClaudeGateway(transport=_stub))
    result = await orch.run(ResearchRequest(names=["n1", "n2"]))
    assert result.outputs["research:n1"]["name"] == "n1"
    assert result.outputs["research:n2"]["name"] == "n2"
