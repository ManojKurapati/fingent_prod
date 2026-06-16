"""API-level tests for Finance Systems & Operations: enqueue -> worker -> status,
SSE progress, and the default-deny SoD guardrail on ERP access changes. Routers are
registered via auto-discovery, so ``create_app`` alone mounts them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(
        store=FakeStore(
            data={
                "rows:gl": "100",
                "rows:ap": "50",
                "sod_conflict:grant-admin": "yes",
                "automation:candidates": "2",
                "kpi:cycle_time": "5",
                "kpi:exceptions": "0",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # finops router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _run_body() -> dict[str, object]:
    return {"period": "FY26", "sources": ["gl", "ap"], "access_changes": ["grant-admin"]}


async def test_pipeline_run_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/finops/pipeline/run", json=_run_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["dashboards-reporting"]["rows"] == 150.0
    assert body["result"]["data-pipelines"]["reconciled"] is True


async def test_pipeline_run_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/finops/pipeline/run", json=_run_body())
    r2 = await client.post("/agents/finops/pipeline/run", json=_run_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_pipeline_run_rejects_empty_sources(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/finops/pipeline/run", json={"period": "FY26", "sources": []})
    assert resp.status_code == 422


async def test_sod_access_change_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/finops/pipeline/run", json=_run_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    access = [r for r in approvals if r["tool_name"] == "finops_access_change"]
    assert len(access) == 1  # default-deny holds the SoD-conflicting change

    decision = await client.post(
        f"/approvals/{access[0]['id']}/approve", json={"approver": "sod-reviewer-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_standalone_access_change_endpoint_holds_conflict(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/finops/erp/access-change", json={"change": "grant-admin", "role": "superuser"}
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["erp-administration"]["gated"] == 1
    approvals = (await client.get("/approvals")).json()
    assert any(r["tool_name"] == "finops_access_change" for r in approvals)


async def test_pipeline_run_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/finops/pipeline/run", json=_run_body())).json()["job_id"]

    received = []

    async def consume() -> None:
        async for ev in context.jobs.progress.subscribe(job_id):
            received.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await context.jobs.drain()
    await context.jobs.progress.close(job_id)
    await asyncio.wait_for(task, timeout=1.0)

    steps = {e.payload["step"] for e in received if e.type == "step"}
    assert {"data-pipelines", "dashboards-reporting", "erp-administration"} <= steps
