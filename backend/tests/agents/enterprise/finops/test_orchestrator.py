"""Orchestrator-graph tests for Finance Systems & Operations.

HYBRID (per ``claude1.md`` §9): a sequential spine ``data-pipelines ->
dashboards-reporting`` plus three independent parallel lanes
(``erp-administration`` ‖ ``process-transformation`` ‖ ``o2c-p2p-process-owner``).
Tests assert the spine dependency, that the independent lanes overlap, and that an
SoD-conflicting access change is held by the default-deny gate. A standalone
SEQUENTIAL access-change path is also asserted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.finops.orchestrator import (
    FinOpsAccessChangeOrchestrator,
    FinOpsOrchestrator,
)
from app.agents.enterprise.finops.schemas import AccessChangeRequest, OperationsRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

# Gateway prompts emitted by the independent root lanes (NOT dashboards, which is
# gated behind the pipeline and would deadlock a roots-only barrier).
_ROOT_PROMPTS = {"run pipeline", "review access", "scan automation", "monitor process KPIs"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "rows:gl": "100",
            "rows:ap": "50",
            "sod_conflict:grant-admin": "yes",
            "automation:candidates": "2",
            "kpi:cycle_time": "5",
            "kpi:exceptions": "0",
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[FinOpsOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = FinOpsOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _request() -> OperationsRequest:
    return OperationsRequest(period="FY26", sources=["gl", "ap"], access_changes=["grant-admin"])


def test_graph_is_hybrid_with_spine_and_parallel_lanes() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # sequential spine: pipelines -> dashboards
    assert by_name["data-pipelines"].depends_on == ()
    assert by_name["dashboards-reporting"].depends_on == ("data-pipelines",)
    # three independent parallel lanes have no dependencies
    assert by_name["erp-administration"].depends_on == ()
    assert by_name["process-transformation"].depends_on == ()
    assert by_name["o2c-p2p-process-owner"].depends_on == ()


async def test_independent_lanes_run_concurrently() -> None:
    """data-pipelines ‖ erp-administration ‖ process-transformation ‖ o2c overlap."""
    barrier = asyncio.Barrier(len(_ROOT_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _ROOT_PROMPTS:
            await barrier.wait()  # only releases if all four roots overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["dashboards-reporting"]["rows"] == 150.0


async def test_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["data-pipelines"] < pos["dashboards-reporting"]


async def test_run_holds_sod_conflicting_change_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())

    erp = result.outputs["erp-administration"]
    assert erp["conflicts"] == ["grant-admin"]
    assert erp["gated"] == 1
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "finops_access_change"

    outcome = await guardrails.approve(pending[0].id, approver="sod-reviewer-jo")
    assert outcome.executed is True


# --- standalone access-change path (sequential) ---------------------------


def test_access_change_graph_is_sequential() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = FinOpsAccessChangeOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    graph = orch.build_graph(AccessChangeRequest(change="grant-admin", role="superuser"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["erp-administration"]


async def test_access_change_run_holds_conflicting_change() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = FinOpsAccessChangeOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    result = await orch.run(AccessChangeRequest(change="grant-admin", role="superuser"))
    assert result.outputs["erp-administration"]["gated"] == 1
    assert len(guardrails.pending()) == 1
