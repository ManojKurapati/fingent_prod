"""API-level tests for Private Markets: enqueue -> worker -> status, SSE progress,
and the default-deny IC capital-commitment gate. The router is auto-discovered, so
``create_app`` alone mounts it.
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
        store=FakeStore(data={"pm:leverage:d1": "4.0", "pm:covenant_headroom:p1": "-0.2"})
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _deal_body(asset_class: str = "credit") -> dict[str, object]:
    return {"deal_id": "d1", "asset_class": asset_class, "sponsor": "acme"}


async def test_deal_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/private-markets/deals", json=_deal_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["credit-underwriting"]["recommendation"] == "invest"


async def test_deal_is_idempotent_on_repeat(client: httpx.AsyncClient, context: AppContext) -> None:
    r1 = await client.post("/agents/private-markets/deals", json=_deal_body())
    r2 = await client.post("/agents/private-markets/deals", json=_deal_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_deal_rejects_unknown_asset_class(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/private-markets/deals", json=_deal_body("crypto"))
    assert resp.status_code == 422


async def test_capital_is_blocked_until_ic_approves(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/private-markets/deals", json=_deal_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    commits = [r for r in approvals if r["tool_name"] == "pm_commit_capital"]
    assert len(commits) == 1  # default-deny holds the capital commitment

    decision = await client.post(
        f"/approvals/{commits[0]['id']}/approve", json={"approver": "ic-chair"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # capital commits only post-approval


async def test_deal_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/private-markets/deals", json=_deal_body())).json()[
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
    assert {"origination-pipeline", "credit-underwriting", "ic-commitment"} <= steps


async def test_monitor_endpoint_runs_sequentially(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/private-markets/monitor", json={"portfolio_id": "p1"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert "covenant" in result["portfolio-stewardship"]["alerts"]
