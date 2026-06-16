"""API-level tests for Investment Banking: enqueue -> worker -> status, SSE
progress, idempotency, and the mandatory compliance gate + default-deny launch.

The router is registered via auto-discovery, so ``create_app`` alone mounts it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _context(*, conflict: str = "clear") -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(
        store=FakeStore(data={"financials:d1": "500", "conflict:acme": conflict})
    )
    return ctx


@pytest.fixture
def context() -> AppContext:
    return _context(conflict="clear")


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body(deal_type: str = "ma") -> dict[str, object]:
    return {"deal_id": "d1", "client": "acme", "deal_type": deal_type, "sector": "tech"}


async def test_mandate_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/investment-banking/mandates", json=_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["compliance-gate"]["decision"] == "PASS"


async def test_mandate_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/investment-banking/mandates", json=_body())
    r2 = await client.post("/agents/investment-banking/mandates", json=_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_mandate_rejects_unknown_deal_type(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/investment-banking/mandates", json=_body("widget"))
    assert resp.status_code == 422


async def test_launch_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/investment-banking/mandates", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    launches = [r for r in approvals if r["tool_name"] == "ib_launch_mandate"]
    assert len(launches) == 1  # default-deny holds the client-facing launch

    decision = await client.post(
        f"/approvals/{launches[0]['id']}/approve", json={"approver": "compliance-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # launch runs only post-approval


async def test_conflicted_mandate_never_queues_a_launch(client: httpx.AsyncClient) -> None:
    ctx = _context(conflict="flagged")
    app = create_app(ctx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/agents/investment-banking/mandates", json=_body())
        await ctx.jobs.drain()
        approvals = (await c.get("/approvals")).json()
        assert [r for r in approvals if r["tool_name"] == "ib_launch_mandate"] == []


async def test_mandate_streams_step_progress(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/investment-banking/mandates", json=_body())).json()[
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
    assert {"coverage-origination", "compliance-gate", "ma-execution"} <= steps
