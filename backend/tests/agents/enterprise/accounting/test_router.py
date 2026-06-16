"""API-level tests for Accounting & Controllership: enqueue -> worker -> status,
SSE progress, and the default-deny guardrail on the GL journal-entry post. The
router is registered via auto-discovery, so ``create_app`` alone mounts it.
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
                "accrual:e1": "300",
                "accrual:e2": "200",
                "asset_cost:e1": "6000",
                "inventory:e1": "1100",
                "std_cost:e1": "1000",
                "contract:e1": "1200",
                "gl_control": "1500",
                "entity_balance:e1": "1000",
                "fx_rate:e1": "1.0",
                "ic:e1": "0",
                "entity_balance:e2": "500",
                "fx_rate:e2": "1.0",
                "ic:e2": "0",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # accounting router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _close_body() -> dict[str, object]:
    return {"period": "FY26-M06", "entities": ["e1", "e2"]}


async def test_close_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/accounting/close/start", json=_close_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    status = await client.get(f"/jobs/{job_id}")
    body = status.json()
    assert body["status"] == "completed"
    assert body["result"]["consolidations"]["group_total"] == pytest.approx(1500.0)


async def test_close_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/accounting/close/start", json=_close_body())
    r2 = await client.post("/agents/accounting/close/start", json=_close_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_close_rejects_empty_entities(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/accounting/close/start", json={"period": "FY26-M06", "entities": []}
    )
    assert resp.status_code == 422


async def test_ledger_post_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/accounting/close/start", json=_close_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    posts = [r for r in approvals if r["tool_name"] == "accounting_post_journal_entry"]
    assert len(posts) == 1  # default-deny holds the GL post

    decision = await client.post(
        f"/approvals/{posts[0]['id']}/approve", json={"approver": "controller-sam"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # posts to GL only post-approval


async def test_close_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/accounting/close/start", json=_close_body())).json()[
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
    assert {"close-orchestration", "reconciliations", "consolidations"} <= steps
