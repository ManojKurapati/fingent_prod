"""API-level tests for Corporate Development & Strategy: enqueue -> worker ->
status, SSE progress, and the default-deny guardrails on deal and earnings
publications. Routers are auto-discovered, so ``create_app`` alone mounts them.
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
                "target:revenue:alpha": "50",
                "target:revenue:beta": "120",
                "target:ebitda:beta": "10",
                "target:redflags:beta": "0",
                "market:saas": "300",
                "market:fintech": "200",
                "ir:consensus": "100",
                "ir:actual": "110",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _deal_body() -> dict[str, object]:
    return {"targets": ["alpha", "beta"], "synergy_rate": 0.1, "ebitda_multiple": 8.0}


def _earnings_body() -> dict[str, object]:
    return {"period": "Q1FY26", "segments": ["saas", "fintech"]}


async def test_deal_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/corpdev/deal", json=_deal_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["deal-materials"]["memo"]["target"] == "beta"


async def test_deal_is_idempotent_on_repeat(client: httpx.AsyncClient, context: AppContext) -> None:
    r1 = await client.post("/agents/corpdev/deal", json=_deal_body())
    r2 = await client.post("/agents/corpdev/deal", json=_deal_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_deal_rejects_empty_targets(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/corpdev/deal", json={"targets": []})
    assert resp.status_code == 422


async def test_deal_recommendation_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/corpdev/deal", json=_deal_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    publish = [r for r in approvals if r["tool_name"] == "corpdev_publish_deal"]
    assert len(publish) == 1

    decision = await client.post(
        f"/approvals/{publish[0]['id']}/approve", json={"approver": "board-chair"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_deal_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/corpdev/deal", json=_deal_body())).json()["job_id"]

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
    assert {"pipeline-sourcing", "valuation-modelling", "deal-materials"} <= steps


async def test_earnings_endpoint_runs_and_holds_publish(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/corpdev/ir/earnings-pack", json=_earnings_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["strategy-analysis"]["tam"] == pytest.approx(500.0)
    assert result["investor-relations"]["pack"]["beat"] is True

    approvals = (await client.get("/approvals")).json()
    publish = [r for r in approvals if r["tool_name"] == "corpdev_publish_earnings"]
    assert len(publish) == 1  # default-deny holds the external IR communication

    decision = await client.post(
        f"/approvals/{publish[0]['id']}/approve", json={"approver": "ir-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # the publish runs only post-approval
