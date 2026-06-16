"""Orchestrator-graph tests for Quantitative, Data & Technology.

Research is PARALLEL by default — six independent workstreams fan out. Promotion
to production is SEQUENTIAL with a mandatory model-validation gate:
``model-validation -> promote`` (research -> validation -> production is strictly
ordered, and promotion is blocked if validation does not clear).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.quantitative_data_technology.orchestrator import (
    QuantPromoteOrchestrator,
    QuantResearchOrchestrator,
)
from app.agents.financial_services.quantitative_data_technology.schemas import (
    PromoteRequest,
    QuantJobsRequest,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_WORKSTREAM_PROMPTS = {
    "price derivatives",
    "research alpha",
    "develop risk model",
    "score data",
    "engineer product",
    "build strategy",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _research(
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
) -> QuantResearchOrchestrator:
    return QuantResearchOrchestrator(gateway=ClaudeGateway(transport=transport))


def _promote(connectors: ToolRegistry) -> tuple[QuantPromoteOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = QuantPromoteOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=connectors,
    )
    return orch, guardrails


def test_research_graph_is_parallel() -> None:
    graph = _research().build_graph(QuantJobsRequest(dataset="eod-prices"))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert all(s.depends_on == () for s in graph.steps)
    assert {s.name for s in graph.steps} == {
        "quant-pricing",
        "quant-research",
        "risk-model-dev",
        "data-science",
        "financial-engineering",
        "systematic-dev",
    }


async def test_research_workstreams_run_concurrently() -> None:
    barrier = asyncio.Barrier(len(_WORKSTREAM_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _WORKSTREAM_PROMPTS:
            await barrier.wait()  # only releases if all six overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    result = await asyncio.wait_for(
        _research(gated).run(QuantJobsRequest(dataset="eod-prices")), timeout=1.0
    )
    assert result.outputs["quant-research"]["candidate"] is True


def test_promote_graph_is_sequential_validation_then_promote() -> None:
    orch, _ = _promote(build_fake_connector(store=FakeStore(data={"validation:VT-1": "approved"})))
    graph = orch.build_graph(PromoteRequest(model_id="M1", validation_token="VT-1"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["model-validation", "promote"]


async def test_promote_held_for_approval_when_validation_passes() -> None:
    orch, guardrails = _promote(
        build_fake_connector(store=FakeStore(data={"validation:VT-1": "approved"}))
    )
    result = await orch.run(PromoteRequest(model_id="M1", validation_token="VT-1"))
    promote = result.outputs["promote"]
    assert promote["blocked"] is False
    assert promote["executed"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "quant_promote_model"


async def test_promote_blocked_when_validation_gate_fails() -> None:
    orch, guardrails = _promote(build_fake_connector(store=FakeStore(data={})))
    result = await orch.run(PromoteRequest(model_id="M1", validation_token=None))
    assert result.outputs["model-validation"]["passed"] is False
    assert result.outputs["promote"]["blocked"] is True
    assert guardrails.pending() == []  # no validation token -> never submitted
