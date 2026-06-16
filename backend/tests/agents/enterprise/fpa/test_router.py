"""API-level tests for FP&A: enqueue -> worker -> status, SSE progress, and the
default-deny guardrail on variance commentary. The FP&A router is registered via
auto-discovery (no shared-registry edits), so ``create_app`` alone mounts it.
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
    # Seed actuals/plan so cc1 breaches its variance threshold and cc2 does not.
    ctx.connectors = build_fake_connector(
        store=FakeStore(
            data={
                "actual:cc1": "120",
                "actual:cc2": "102",
                "plan:cc1": "100",
                "plan:cc2": "100",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # fpa router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _forecast_body() -> dict[str, object]:
    return {"period": "FY26", "cost_centres": ["cc1", "cc2"], "variance_threshold": 0.1}


async def test_forecast_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/fpa/forecast", json=_forecast_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    status = await client.get(f"/jobs/{job_id}")
    body = status.json()
    assert body["status"] == "completed"
    assert body["result"]["reporting-packs"]["pack"]["cost_centres"] == 2


async def test_forecast_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    # The endpoint passes the same idempotency key, so a re-post returns the job.
    r1 = await client.post("/agents/fpa/forecast", json=_forecast_body())
    r2 = await client.post("/agents/fpa/forecast", json=_forecast_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_forecast_rejects_empty_cost_centres(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/fpa/forecast", json={"period": "FY26", "cost_centres": []})
    assert resp.status_code == 422


async def test_breach_commentary_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/fpa/forecast", json=_forecast_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    commentary = [r for r in approvals if r["tool_name"] == "fpa_request_commentary"]
    assert len(commentary) == 1  # only cc1 breached; default-deny holds it

    decision = await client.post(
        f"/approvals/{commentary[0]['id']}/approve", json={"approver": "fpa-manager-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # the owner ping runs only post-approval


async def test_forecast_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/fpa/forecast", json=_forecast_body())).json()["job_id"]

    received = []

    async def consume() -> None:
        async for ev in context.jobs.progress.subscribe(job_id):
            received.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber register before events publish
    await context.jobs.drain()
    await context.jobs.progress.close(job_id)
    await asyncio.wait_for(task, timeout=1.0)

    steps = {e.payload["step"] for e in received if e.type == "step"}
    assert {"data-intake", "budget-consolidation", "reporting-packs"} <= steps


async def test_scenario_endpoint_runs_sequentially(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/fpa/scenario",
        json={"period": "FY26", "cost_centres": ["cc1", "cc2"], "drivers": {"price": 0.1}},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["scenario-modelling"]["base"] == pytest.approx(222.0)
    assert result["scenario-modelling"]["adjusted"] == pytest.approx(244.2)
