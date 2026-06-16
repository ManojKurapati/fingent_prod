"""Orchestrator-graph tests for Treasury.

``claude1.md`` §5 documents Treasury as a **sequential dependency chain**
(``cash-positioning -> liquidity-forecasting``) with a **parallel tail**
(``fx-hedging`` ‖ ``debt-covenants``, both consuming the forecast) and
``bank-connectivity`` as an independent standing service. A strictly-linear
SEQUENTIAL graph cannot express a parallel tail, so the realised graph mode is
HYBRID — these tests assert BOTH the sequential spine ordering AND that the tail
runs concurrently, faithfully honouring the documented flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.treasury.orchestrator import TreasuryDailyPositionOrchestrator
from app.agents.enterprise.treasury.schemas import DailyPositionRequest
from app.connectors import FakeStore, ToolRegistry, build_fake_connector

_TAIL_STEPS = {"hedge exposures", "check covenants"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "balance:a1": "1000",
            "bank:a1": "1000",
            "ar": "400",
            "ap": "150",
            "fx:EUR": "300",
            "debt": "2000",
            "ebitda": "1000",
            "active_banks": "2",
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> TreasuryDailyPositionOrchestrator:
    return TreasuryDailyPositionOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        connectors=connectors or _seeded_connectors(),
    )


def _request() -> DailyPositionRequest:
    return DailyPositionRequest(as_of="2026-06-16", accounts=["a1"])


def test_graph_is_hybrid_sequential_spine_with_parallel_tail() -> None:
    orch = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # sequential spine: cash-positioning -> liquidity-forecasting
    assert by_name["cash-positioning"].depends_on == ()
    assert by_name["liquidity-forecasting"].depends_on == ("cash-positioning",)
    # parallel tail: both depend ONLY on the forecast, not each other
    assert by_name["fx-hedging"].depends_on == ("liquidity-forecasting",)
    assert by_name["debt-covenants"].depends_on == ("liquidity-forecasting",)
    # bank-connectivity is an independent standing service (no deps)
    assert by_name["bank-connectivity"].depends_on == ()


async def test_parallel_tail_runs_concurrently() -> None:
    """fx-hedging ‖ debt-covenants must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_TAIL_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _TAIL_STEPS:
            await barrier.wait()  # only releases if both tail steps overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert "fx-hedging" in result.outputs
    assert "debt-covenants" in result.outputs


async def test_sequential_spine_ordering_holds() -> None:
    orch = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    # cannot forecast liquidity without the cash position
    assert pos["cash-positioning"] < pos["liquidity-forecasting"]
    # cannot hedge / assess covenants without the forecast
    assert pos["liquidity-forecasting"] < pos["fx-hedging"]
    assert pos["liquidity-forecasting"] < pos["debt-covenants"]


async def test_run_produces_dashboard_payload() -> None:
    orch = _orchestrator()
    result = await orch.run(_request())
    assert result.outputs["cash-positioning"]["position"] == 1000.0
    assert result.outputs["liquidity-forecasting"]["forecast"] == 1250.0  # 1000 + 400 - 150
    assert result.outputs["fx-hedging"]["proposed_hedge"] == 300.0
    assert result.outputs["debt-covenants"]["leverage"] == 2.0
