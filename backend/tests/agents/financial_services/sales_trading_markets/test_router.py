"""API-level tests for Sales & Trading / Markets: enqueue -> worker -> status, SSE
progress, idempotency, and the mandatory pre-trade risk gate + default-deny routing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _context(*, limit: str = "1000", exposure: str = "100") -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(
        store=FakeStore(
            data={
                "price:AAPL": "10",
                "limit:eqbook": limit,
                "exposure:eqbook": exposure,
                "suitable:acct1": "yes",
            }
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
    body: dict[str, object] = {
        "order_id": "o1",
        "account": "acct1",
        "instrument": "AAPL",
        "side": "buy",
        "quantity": 5.0,
        "book": "eqbook",
    }
    body.update(overrides)
    return body


async def test_order_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/sales-trading-markets/orders", json=_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()
    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["pre-trade-risk-gate"]["decision"] == "PASS"


async def test_order_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/sales-trading-markets/orders", json=_body())
    r2 = await client.post("/agents/sales-trading-markets/orders", json=_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_order_rejects_invalid_side(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/sales-trading-markets/orders", json=_body(side="hodl"))
    assert resp.status_code == 422


async def test_order_rejects_nonpositive_quantity(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/sales-trading-markets/orders", json=_body(quantity=0))
    assert resp.status_code == 422


async def test_routing_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/sales-trading-markets/orders", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    routes = [r for r in approvals if r["tool_name"] == "markets_route_order"]
    assert len(routes) == 1  # default-deny holds the order routing

    decision = await client.post(
        f"/approvals/{routes[0]['id']}/approve", json={"approver": "trader-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_over_limit_order_never_queues_routing(client: httpx.AsyncClient) -> None:
    ctx = _context(limit="120", exposure="100")
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/agents/sales-trading-markets/orders", json=_body())
        await ctx.jobs.drain()
        approvals = (await c.get("/approvals")).json()
        assert [r for r in approvals if r["tool_name"] == "markets_route_order"] == []


async def test_order_streams_step_progress(client: httpx.AsyncClient, context: AppContext) -> None:
    job_id = (await client.post("/agents/sales-trading-markets/orders", json=_body())).json()[
        "job_id"
    ]

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
    assert {"pricing-quoting", "pre-trade-risk-gate", "execution-algo"} <= steps
