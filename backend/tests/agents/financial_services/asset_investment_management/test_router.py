"""API-level tests for Asset & Investment Management: enqueue -> worker -> status,
SSE progress, idempotency, the standalone research fan-out, and the mandatory
mandate/risk gate + default-deny order placement.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _context(*, limit: str = "1000") -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(
        store=FakeStore(
            data={"target:n1": "50", "target:n2": "50", "limit:pf1": limit, "liquidity:pf1": "ok"}
        )
    )
    return ctx


@pytest.fixture
def context() -> AppContext:
    return _context()


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"portfolio_id": "pf1", "names": ["n1", "n2"], "period": "FY26"}
    body.update(overrides)
    return body


async def test_rebalance_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/asset-investment-management/rebalance", json=_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()
    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["mandate-risk-gate"]["decision"] == "PASS"


async def test_rebalance_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/asset-investment-management/rebalance", json=_body())
    r2 = await client.post("/agents/asset-investment-management/rebalance", json=_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_rebalance_rejects_empty_names(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/asset-investment-management/rebalance", json=_body(names=[]))
    assert resp.status_code == 422


async def test_order_placement_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/asset-investment-management/rebalance", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    placements = [r for r in approvals if r["tool_name"] == "aim_place_orders"]
    assert len(placements) == 1

    decision = await client.post(
        f"/approvals/{placements[0]['id']}/approve", json={"approver": "pm-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_over_limit_rebalance_never_queues_placement(client: httpx.AsyncClient) -> None:
    ctx = _context(limit="50")
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/agents/asset-investment-management/rebalance", json=_body())
        await ctx.jobs.drain()
        approvals = (await c.get("/approvals")).json()
        assert [r for r in approvals if r["tool_name"] == "aim_place_orders"] == []


async def test_research_endpoint_runs_fanout(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/asset-investment-management/research", json={"names": ["n1", "n2"]}
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["research:n1"]["name"] == "n1"
    assert result["research:n2"]["name"] == "n2"


async def test_rebalance_streams_step_progress(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (
        await client.post("/agents/asset-investment-management/rebalance", json=_body())
    ).json()["job_id"]

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
    assert {"macro-strategy", "mandate-risk-gate", "buyside-execution"} <= steps
