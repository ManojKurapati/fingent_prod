"""Tests for the reference template group-agent (the wave 2/3 copy target)."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.agents._template.orchestrator import TemplateOrchestrator
from app.agents._template.router import router as template_router
from app.agents._template.schemas import RunRequest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion, StepEvent
from app.api.context import AppContext, build_context
from app.main import create_app


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=3, output_tokens=2)


def _orchestrator(ctx: AppContext) -> TemplateOrchestrator:
    return TemplateOrchestrator(gateway=ctx.gateway, guardrails=ctx.guardrails)


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.gateway = ClaudeGateway(transport=_stub_transport)
    return ctx


def test_graph_is_hybrid_with_intake_head_and_report_fanin() -> None:
    ctx = build_context()
    graph = _orchestrator(ctx).build_graph(RunRequest(cost_centres=["cc1", "cc2"]))
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # intake is the sequential head
    assert by_name["data-intake"].depends_on == ()
    # analyses fan out from intake, independent of each other
    assert by_name["analyze:cc1"].depends_on == ("data-intake",)
    assert by_name["analyze:cc2"].depends_on == ("data-intake",)
    # report fans in from intake + every analysis
    assert set(by_name["reporting-pack"].depends_on) == {
        "data-intake",
        "analyze:cc1",
        "analyze:cc2",
    }


async def test_analyses_run_concurrently(context: AppContext) -> None:
    """The two analysis subagents must overlap (proves PARALLEL fan-out)."""
    barrier = asyncio.Barrier(2)

    async def slow_transport(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt.startswith("analyze"):
            await barrier.wait()  # deadlocks unless the analyses overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    context.gateway = ClaudeGateway(transport=slow_transport)
    orch = _orchestrator(context)
    result = await asyncio.wait_for(orch.run(RunRequest(cost_centres=["a", "b"])), timeout=1.0)
    assert result.outputs["reporting-pack"]["pack"]["sections"] == 2


async def test_report_routes_publish_through_guardrail_default_deny(
    context: AppContext,
) -> None:
    orch = _orchestrator(context)
    result = await orch.run(RunRequest(cost_centres=["a"]))

    report = result.outputs["reporting-pack"]
    # consequential publish is NOT executed; it is held for approval
    assert report["published"] is False
    assert report["approval_id"] is not None
    assert len(context.guardrails.pending()) == 1


async def test_run_emits_step_progress_events(context: AppContext) -> None:
    events: list[StepEvent] = []

    async def sink(ev: StepEvent) -> None:
        events.append(ev)

    await _orchestrator(context).run(RunRequest(cost_centres=["a"]), emit=sink)
    steps = {e.step for e in events}
    assert {"data-intake", "analyze:a", "reporting-pack"} <= steps


# --- router / API level ---------------------------------------------------


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    app.include_router(template_router)  # _template is not auto-discovered by design
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_run_endpoint_enqueues_job_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/template/run", json={"cost_centres": ["a", "b"]})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    status = await client.get(f"/jobs/{job_id}")
    assert status.json()["status"] == "completed"

    # the consequential publish surfaced in the shared approvals queue
    approvals = await client.get("/approvals")
    assert any(r["tool_name"] == "template_publish" for r in approvals.json())


async def test_run_endpoint_rejects_empty_cost_centres(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/template/run", json={"cost_centres": []})
    assert resp.status_code == 422


async def test_approving_publish_executes_consequential_action(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/template/run", json={"cost_centres": ["a"]})
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    publish = next(r for r in approvals if r["tool_name"] == "template_publish")

    decision = await client.post(
        f"/approvals/{publish['id']}/approve", json={"approver": "controller-jane"}
    )
    assert decision.status_code == 200
    body = decision.json()
    assert body["executed"] is True  # the publish actually ran post-approval
    assert body["request"]["state"] == "approved"
