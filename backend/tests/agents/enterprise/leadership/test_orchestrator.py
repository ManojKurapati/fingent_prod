"""Orchestrator-graph tests for Leadership.

Asserts the hybrid shape (sequential spine ``divisional-rollup -> capital-strategy``
with a parallel fan-out of the standing lanes), that the independent fan-out steps
run *concurrently*, that the spine ordering holds, and that the standalone capital
path is sequential.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.leadership.orchestrator import (
    LeadershipCapitalOrchestrator,
    LeadershipOrchestrator,
)
from app.agents.enterprise.leadership.schemas import BoardPackRequest, CapitalScenarioRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

# The three steps that gate only on divisional-rollup and so fan out together.
_FANOUT_GATEWAY_STEPS = {
    "model capital structure",
    "stage budget signoff",
    "prioritise transformation initiatives",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "pnl:emea": "100",
            "pnl:amer": "150",
            "capital:debt": "60",
            "capital:equity": "40",
            "budget:plan": "200",
            "initiatives:count": "3",
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[LeadershipOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = LeadershipOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _request() -> BoardPackRequest:
    return BoardPackRequest(period="FY26", divisions=["emea", "amer"], target_leverage=0.4)


def test_graph_is_hybrid_with_spine_fanout_and_partial_fanin() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # consolidation head, then the three independent lanes gate only on it
    assert by_name["divisional-rollup"].depends_on == ()
    assert by_name["capital-strategy"].depends_on == ("divisional-rollup",)
    assert by_name["budget-plan-signoff"].depends_on == ("divisional-rollup",)
    assert by_name["transformation-sponsor"].depends_on == ("divisional-rollup",)
    # board reporting is a partial fan-in: needs consolidated view + capital decision
    assert set(by_name["board-investor-reporting"].depends_on) == {
        "divisional-rollup",
        "capital-strategy",
    }


async def test_fanout_steps_run_concurrently() -> None:
    """capital ‖ budget ‖ transformation must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_FANOUT_GATEWAY_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _FANOUT_GATEWAY_STEPS:
            await barrier.wait()  # only releases if all three overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["board-investor-reporting"]["pack"]["group_pnl"] == pytest.approx(250.0)


async def test_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["divisional-rollup"] < pos["capital-strategy"]
    assert pos["capital-strategy"] < pos["board-investor-reporting"]
    assert pos["divisional-rollup"] < pos["budget-plan-signoff"]


async def test_run_holds_board_pack_publish_for_approval() -> None:
    orch, guardrails = _orchestrator()
    await orch.run(_request())
    pending = guardrails.pending()
    # two consequential gates: external board-pack publish + annual budget sign-off
    tool_names = {p.tool_name for p in pending}
    assert tool_names == {"leadership_publish_board_pack", "leadership_approve_budget"}


# --- standalone capital-scenario path (sequential) -------------------------


def test_capital_scenario_graph_is_sequential() -> None:
    orch = LeadershipCapitalOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_seeded_connectors()
    )
    graph = orch.build_graph(
        CapitalScenarioRequest(period="FY26", divisions=["emea"], target_leverage=0.5)
    )
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["divisional-rollup", "capital-strategy"]


async def test_capital_scenario_run_applies_target_leverage() -> None:
    orch = LeadershipCapitalOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_seeded_connectors()
    )
    result = await orch.run(
        CapitalScenarioRequest(period="FY26", divisions=["emea", "amer"], target_leverage=0.7)
    )
    capital = result.outputs["capital-strategy"]
    assert capital["leverage"] == pytest.approx(0.6)
    assert capital["recommendation"] == "raise_debt"  # 0.6 < 0.7 target
