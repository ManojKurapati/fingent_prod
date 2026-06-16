"""Orchestrator-graph tests for FP&A.

Asserts the hybrid shape (sequential spine + parallel fan-out + fan-in), that the
fan-out steps actually run *concurrently*, that the spine ordering holds, and that
the standalone scenario path is sequential.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.fpa.orchestrator import FpaOrchestrator, FpaScenarioOrchestrator
from app.agents.enterprise.fpa.schemas import ForecastRequest, ScenarioRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_FANOUT_GATEWAY_STEPS = {"run forecast", "analyze revenue", "model scenario"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "actual:cc1": "120",  # 20% over plan -> breach
            "actual:cc2": "102",  # 2% over plan -> within threshold
            "plan:cc1": "100",
            "plan:cc2": "100",
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[FpaOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = FpaOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _request() -> ForecastRequest:
    return ForecastRequest(period="FY26", cost_centres=["cc1", "cc2"], variance_threshold=0.1)


def test_graph_is_hybrid_with_spine_fanout_and_fanin() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # sequential spine: intake -> consolidation
    assert by_name["data-intake"].depends_on == ()
    assert by_name["budget-consolidation"].depends_on == ("data-intake",)
    # parallel fan-out gates on the spine, mutually independent
    assert by_name["forecast-engine"].depends_on == ("budget-consolidation",)
    assert by_name["revenue-analytics"].depends_on == ("budget-consolidation",)
    assert by_name["scenario-modelling"].depends_on == ("data-intake",)
    assert set(by_name["variance:cc1"].depends_on) == {"data-intake", "budget-consolidation"}
    assert set(by_name["variance:cc2"].depends_on) == {"data-intake", "budget-consolidation"}
    # fan-in: reporting depends on every fan-out branch
    assert set(by_name["reporting-packs"].depends_on) == {
        "forecast-engine",
        "revenue-analytics",
        "scenario-modelling",
        "variance:cc1",
        "variance:cc2",
    }


async def test_fanout_steps_run_concurrently() -> None:
    """forecast ‖ revenue ‖ scenario must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_FANOUT_GATEWAY_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _FANOUT_GATEWAY_STEPS:
            await barrier.wait()  # only releases if all three overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["reporting-packs"]["pack"]["cost_centres"] == 2


async def test_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    # intake before consolidation before each consolidation-gated fan-out step
    assert pos["data-intake"] < pos["budget-consolidation"]
    assert pos["budget-consolidation"] < pos["forecast-engine"]
    assert pos["budget-consolidation"] < pos["variance:cc1"]
    # reporting-packs fans in last
    assert result.order[-1] == "reporting-packs"


async def test_run_holds_breach_commentary_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())

    by_cc = {
        result.outputs[f"variance:{cc}"]["cost_centre"]: result.outputs[f"variance:{cc}"]
        for cc in ("cc1", "cc2")
    }
    assert by_cc["cc1"]["breach"] is True
    assert by_cc["cc2"]["breach"] is False
    # exactly one consequential commentary request is held (default-deny)
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "fpa_request_commentary"
    assert result.outputs["reporting-packs"]["breaches"] == ["cc1"]


# --- standalone scenario path (sequential) --------------------------------


def test_scenario_graph_is_sequential() -> None:
    orch = FpaScenarioOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_seeded_connectors()
    )
    graph = orch.build_graph(
        ScenarioRequest(period="FY26", cost_centres=["cc1", "cc2"], drivers={"price": 0.1})
    )
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["data-intake", "scenario-modelling"]


async def test_scenario_run_applies_drivers() -> None:
    orch = FpaScenarioOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_seeded_connectors()
    )
    result = await orch.run(
        ScenarioRequest(period="FY26", cost_centres=["cc1", "cc2"], drivers={"price": 0.1})
    )
    scenario = result.outputs["scenario-modelling"]
    assert scenario["base"] == pytest.approx(222.0)  # 120 + 102
    assert scenario["adjusted"] == pytest.approx(244.2)
