"""Orchestrator-graph tests for Insurance.

Asserts the submission hybrid shape (``actuarial`` ‖ ``cat-modelling`` ->
``underwriting``), that the two priced inputs actually run *concurrently*, and that
the portfolio path is PARALLEL and the claims path SEQUENTIAL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.insurance.orchestrator import (
    InsuranceClaimsOrchestrator,
    InsurancePortfolioOrchestrator,
    InsuranceSubmissionOrchestrator,
)
from app.agents.financial_services.insurance.schemas import (
    ClaimRequest,
    PortfolioRequest,
    SubmissionRequest,
)
from app.connectors import FakeStore, ToolRegistry, build_fake_connector

_FANOUT_PROMPTS = {"actuarial rate", "cat model"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors() -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(
            data={
                "rate:US-FL": "0.03",
                "catfactor:hurricane": "0.1",
                "accumulation:US-FL:hurricane": "100000",
                "limit:US-FL:hurricane": "500000",
                "grossexposure:US-FL": "1000000",
                "retention:US-FL": "400000",
                "combinedratio:homeowners": "0.92",
            }
        )
    )


def _submission_orch(
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
) -> InsuranceSubmissionOrchestrator:
    return InsuranceSubmissionOrchestrator(
        gateway=ClaudeGateway(transport=transport), connectors=_connectors()
    )


def _request() -> SubmissionRequest:
    return SubmissionRequest(submission_id="S1", region="US-FL", peril="hurricane", tiv=1_000_000.0)


def test_submission_graph_is_hybrid_join() -> None:
    graph = _submission_orch().build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID
    by_name = {s.name: s for s in graph.steps}
    assert by_name["actuarial"].depends_on == ()
    assert by_name["cat-modelling"].depends_on == ()
    assert set(by_name["underwriting"].depends_on) == {"actuarial", "cat-modelling"}


async def test_submission_fanout_runs_concurrently() -> None:
    """actuarial ‖ cat-modelling must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_FANOUT_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _FANOUT_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    result = await asyncio.wait_for(_submission_orch(gated).run(_request()), timeout=1.0)
    assert result.outputs["underwriting"]["within_appetite"] is True


async def test_submission_underwriting_runs_after_pricing() -> None:
    result = await _submission_orch().run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["actuarial"] < pos["underwriting"]
    assert pos["cat-modelling"] < pos["underwriting"]
    assert result.order[-1] == "underwriting"


def test_portfolio_graph_is_parallel() -> None:
    orch = InsurancePortfolioOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_connectors()
    )
    graph = orch.build_graph(PortfolioRequest(region="US-FL", product="homeowners"))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert {s.name for s in graph.steps} == {"reinsurance", "product"}
    assert all(s.depends_on == () for s in graph.steps)


async def test_portfolio_run_produces_both_outputs() -> None:
    orch = InsurancePortfolioOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_connectors()
    )
    result = await orch.run(PortfolioRequest(region="US-FL", product="homeowners"))
    assert result.outputs["reinsurance"]["ceded"] == pytest.approx(600_000.0)
    assert result.outputs["product"]["profitable"] is True


def test_claims_graph_is_sequential() -> None:
    orch = InsuranceClaimsOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_connectors()
    )
    graph = orch.build_graph(ClaimRequest(claim_id="CLM1", amount=50_000.0))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["claims"]
