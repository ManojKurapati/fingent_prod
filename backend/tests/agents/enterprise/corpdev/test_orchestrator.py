"""Orchestrator-graph tests for Corporate Development & Strategy.

Asserts the hybrid deal spine (``pipeline-sourcing -> (valuation ‖ diligence) ->
deal-materials``) with the diligence/valuation pair running *concurrently*, and the
standalone earnings/standing path running two independent lanes in PARALLEL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.corpdev.orchestrator import (
    CorpDevDealOrchestrator,
    CorpDevStandingOrchestrator,
)
from app.agents.enterprise.corpdev.schemas import DealRequest, EarningsPackRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_DEAL_PARALLEL_STEPS = {"build valuation model", "run due diligence"}
_STANDING_PARALLEL_STEPS = {"analyse market", "draft earnings release"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "target:revenue:alpha": "50",
            "target:revenue:beta": "120",
            "target:ebitda:beta": "10",
            "target:redflags:beta": "0",
            "market:saas": "300",
            "market:fintech": "200",
            "ir:consensus": "100",
            "ir:actual": "110",
        }
    )
    return build_fake_connector(store=store)


def _deal_orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
) -> tuple[CorpDevDealOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = CorpDevDealOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    return orch, guardrails


def _standing_orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
) -> tuple[CorpDevStandingOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = CorpDevStandingOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    return orch, guardrails


def _deal_request() -> DealRequest:
    return DealRequest(targets=["alpha", "beta"], synergy_rate=0.1, ebitda_multiple=8.0)


def _earnings_request() -> EarningsPackRequest:
    return EarningsPackRequest(period="Q1FY26", segments=["saas", "fintech"])


# --- deal orchestrator (hybrid) --------------------------------------------


def test_deal_graph_is_hybrid_with_parallel_diligence_and_fanin() -> None:
    orch, _ = _deal_orchestrator()
    graph = orch.build_graph(_deal_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["pipeline-sourcing"].depends_on == ()
    # valuation ‖ due-diligence both gate on sourcing (run together)
    assert by_name["valuation-modelling"].depends_on == ("pipeline-sourcing",)
    assert by_name["due-diligence"].depends_on == ("pipeline-sourcing",)
    # deal-materials fans in both
    assert set(by_name["deal-materials"].depends_on) == {
        "valuation-modelling",
        "due-diligence",
    }


async def test_deal_valuation_and_diligence_run_concurrently() -> None:
    barrier = asyncio.Barrier(len(_DEAL_PARALLEL_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _DEAL_PARALLEL_STEPS:
            await barrier.wait()  # deadlocks unless both overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _deal_orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_deal_request()), timeout=1.0)
    assert result.outputs["deal-materials"]["recommendation"] == "proceed"


async def test_deal_spine_ordering_holds() -> None:
    orch, _ = _deal_orchestrator()
    result = await orch.run(_deal_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["pipeline-sourcing"] < pos["valuation-modelling"]
    assert pos["pipeline-sourcing"] < pos["due-diligence"]
    assert result.order[-1] == "deal-materials"


async def test_deal_holds_recommendation_publish_for_approval() -> None:
    orch, guardrails = _deal_orchestrator()
    await orch.run(_deal_request())
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "corpdev_publish_deal"


# --- standing/IR orchestrator (parallel) -----------------------------------


def test_standing_graph_is_parallel_with_independent_lanes() -> None:
    orch, _ = _standing_orchestrator()
    graph = orch.build_graph(_earnings_request())
    assert graph.mode is OrchestrationMode.PARALLEL
    by_name = {s.name: s for s in graph.steps}
    assert by_name["strategy-analysis"].depends_on == ()
    assert by_name["investor-relations"].depends_on == ()


async def test_standing_lanes_run_concurrently() -> None:
    barrier = asyncio.Barrier(len(_STANDING_PARALLEL_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _STANDING_PARALLEL_STEPS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _standing_orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_earnings_request()), timeout=1.0)
    assert result.outputs["strategy-analysis"]["tam"] == pytest.approx(500.0)


async def test_standing_holds_earnings_publish_for_approval() -> None:
    orch, guardrails = _standing_orchestrator()
    await orch.run(_earnings_request())
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "corpdev_publish_earnings"
