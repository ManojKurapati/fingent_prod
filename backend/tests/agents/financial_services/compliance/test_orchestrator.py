"""Orchestrator-graph tests for Compliance, Legal & Financial Crime.

Asserts the screening hybrid shape (``aml-kyc`` ‖ ``sanctions-screening`` ->
``fraud-investigation`` disposition), that the two screens run concurrently, and
that the continuous-functions path is PARALLEL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.compliance.orchestrator import (
    ComplianceContinuousOrchestrator,
    ComplianceScreenOrchestrator,
)
from app.agents.financial_services.compliance.schemas import ContinuousRequest, ScreenRequest
from app.connectors import FakeStore, ToolRegistry, build_fake_connector

_SCREEN_PROMPTS = {"aml kyc", "sanctions screen"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(**overrides: str) -> ToolRegistry:
    data = {
        "kycrisk:cust1": "low",
        "sanctions:cust1": "0",
        "incidents": "3",
        "filings": "2",
        "contracts": "5",
    }
    data.update(overrides)
    return build_fake_connector(store=FakeStore(data=data))


def _screen_orch(
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> ComplianceScreenOrchestrator:
    return ComplianceScreenOrchestrator(
        gateway=ClaudeGateway(transport=transport), connectors=connectors or _connectors()
    )


def test_screen_graph_is_hybrid_with_disposition_join() -> None:
    graph = _screen_orch().build_graph(ScreenRequest(subject="cust1"))
    assert graph.mode is OrchestrationMode.HYBRID
    by_name = {s.name: s for s in graph.steps}
    assert by_name["aml-kyc"].depends_on == ()
    assert by_name["sanctions-screening"].depends_on == ()
    assert set(by_name["fraud-investigation"].depends_on) == {"aml-kyc", "sanctions-screening"}


async def test_screens_run_concurrently() -> None:
    """aml-kyc ‖ sanctions-screening must overlap (barrier deadlocks otherwise)."""
    barrier = asyncio.Barrier(len(_SCREEN_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _SCREEN_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    result = await asyncio.wait_for(
        _screen_orch(gated).run(ScreenRequest(subject="cust1")), timeout=1.0
    )
    assert result.outputs["fraud-investigation"]["cleared"] is True


async def test_disposition_joins_last_and_clears_clean_subject() -> None:
    result = await _screen_orch().run(ScreenRequest(subject="cust1"))
    assert result.order[-1] == "fraud-investigation"
    assert result.outputs["fraud-investigation"]["cleared"] is True


async def test_disposition_escalates_sanctioned_subject() -> None:
    orch = _screen_orch(connectors=_connectors(**{"sanctions:cust1": "1"}))
    result = await orch.run(ScreenRequest(subject="cust1"))
    disp = result.outputs["fraud-investigation"]
    assert disp["cleared"] is False
    assert disp["sar_recommended"] is True


def test_continuous_graph_is_parallel() -> None:
    orch = ComplianceContinuousOrchestrator(
        gateway=ClaudeGateway(transport=_stub), connectors=_connectors()
    )
    graph = orch.build_graph(ContinuousRequest(scope="firm"))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert {s.name for s in graph.steps} == {
        "compliance-monitoring",
        "regulatory-affairs",
        "legal-counsel",
    }
    assert all(s.depends_on == () for s in graph.steps)
