"""Orchestrator-graph tests for Risk Management.

Asserts the documented shape — a parallel fan-out of the five measures into a
sequential ``erm-aggregation`` barrier — that the measures actually run
concurrently, and that aggregation joins last.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.risk.orchestrator import RiskRunOrchestrator
from app.agents.financial_services.risk.schemas import RiskRunRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_MEASURES = {
    "market-risk",
    "credit-risk",
    "operational-risk",
    "liquidity-risk",
    "model-validation",
}
_MEASURE_PROMPTS = {
    "market risk",
    "credit risk",
    "operational risk",
    "liquidity risk",
    "model validation",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(**overrides: str) -> ToolRegistry:
    data = {
        "var:trading": "80",
        "varlimit:trading": "100",
        "ecl:trading": "40",
        "ecllimit:trading": "50",
        "oploss:trading": "10",
        "oplosslimit:trading": "50",
        "lcr:trading": "1.2",
        "lcrmin:trading": "1.0",
        "modeldrift:trading": "0.05",
        "driftlimit:trading": "0.1",
    }
    data.update(overrides)
    return build_fake_connector(store=FakeStore(data=data))


def _orch(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[RiskRunOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = RiskRunOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def _request() -> RiskRunRequest:
    return RiskRunRequest(as_of="2026-06-16", book="trading")


def test_graph_is_hybrid_fanout_into_aggregation() -> None:
    orch, _ = _orch()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID
    by_name = {s.name: s for s in graph.steps}
    for measure in _MEASURES:
        assert by_name[measure].depends_on == ()
    assert set(by_name["erm-aggregation"].depends_on) == _MEASURES


async def test_measures_run_concurrently() -> None:
    """The five measures must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_MEASURE_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _MEASURE_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orch(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["erm-aggregation"]["within_appetite"] is True


async def test_aggregation_joins_last() -> None:
    orch, _ = _orch()
    result = await orch.run(_request())
    assert result.order[-1] == "erm-aggregation"


async def test_breach_escalates_to_cro_held_for_approval() -> None:
    orch, guardrails = _orch(connectors=_connectors(**{"var:trading": "150"}))
    result = await orch.run(_request())
    agg = result.outputs["erm-aggregation"]
    assert agg["within_appetite"] is False
    assert "market-risk" in agg["breaches"]
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "risk_request_limit_override"
