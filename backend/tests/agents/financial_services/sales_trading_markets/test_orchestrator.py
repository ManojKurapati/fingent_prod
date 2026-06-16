"""Orchestrator-graph tests for Sales & Trading / Markets.

Asserts the HYBRID shape with a hard sequential pre-trade risk gate: four parallel
feeds fan in to the MANDATORY ``pre-trade-risk-gate``; only on PASS does
``execution-algo`` route the order; ``risk-hedging`` re-hedges post-fill.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.sales_trading_markets.orchestrator import (
    SalesTradingOrchestrator,
)
from app.agents.financial_services.sales_trading_markets.schemas import OrderRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_FEED_PROMPTS = {"cover accounts", "quote price", "scan signals", "structure payoff"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(*, limit: str = "1000", exposure: str = "100") -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(
            data={
                "price:AAPL": "10",
                "limit:eqbook": limit,
                "exposure:eqbook": exposure,
                "suitable:acct1": "yes",
            }
        )
    )


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[SalesTradingOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = SalesTradingOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def _request() -> OrderRequest:
    return OrderRequest(
        order_id="o1", account="acct1", instrument="AAPL", side="buy", quantity=5.0, book="eqbook"
    )


def test_graph_is_hybrid_with_feeds_gate_and_gated_execution() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    for feed in ("sales-coverage", "pricing-quoting", "quant-signals", "structuring"):
        assert by_name[feed].depends_on == ()
    # the mandatory gate joins on every feed
    assert set(by_name["pre-trade-risk-gate"].depends_on) == {
        "sales-coverage",
        "pricing-quoting",
        "quant-signals",
        "structuring",
    }
    # execution is gated; hedging is post-fill
    assert by_name["execution-algo"].depends_on == ("pre-trade-risk-gate",)
    assert by_name["risk-hedging"].depends_on == ("execution-algo",)


async def test_feeds_run_concurrently() -> None:
    """The four feeds must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_FEED_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _FEED_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["pre-trade-risk-gate"]["decision"] == "PASS"


async def test_clean_run_holds_route_order_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())
    assert result.outputs["pre-trade-risk-gate"]["decision"] == "PASS"
    assert result.outputs["execution-algo"]["blocked"] is False
    assert result.outputs["execution-algo"]["routed"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "markets_route_order"


async def test_over_limit_run_blocks_routing_before_the_gate() -> None:
    orch, guardrails = _orchestrator(connectors=_connectors(limit="120", exposure="100"))
    result = await orch.run(_request())
    assert result.outputs["pre-trade-risk-gate"]["decision"] == "DENY"
    assert result.outputs["execution-algo"]["blocked"] is True
    assert guardrails.pending() == []  # routing never reaches the approval queue


async def test_ordering_is_feeds_then_gate_then_execution_then_hedge() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    for feed in ("sales-coverage", "pricing-quoting", "quant-signals", "structuring"):
        assert pos[feed] < pos["pre-trade-risk-gate"]
    assert pos["pre-trade-risk-gate"] < pos["execution-algo"] < pos["risk-hedging"]
