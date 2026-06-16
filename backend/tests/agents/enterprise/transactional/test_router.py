"""API-level tests for Transactional / Operational Finance: enqueue -> worker ->
status, SSE progress, and the default-deny cash-movement gate. The router is
registered via auto-discovery, so ``create_app`` alone mounts it.
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
                "invoice:v1": "500",
                "po:v1": "500",
                "invoice:v2": "200",
                "po:v2": "200",
                "payroll:e1": "1000",
                "spend:total": "80",
                "budget:total": "100",
                "contract:c1": "300",
                "contract:c2": "150",
                "cash:c1": "300",
                "cash:c2": "100",
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


def _cycle_body() -> dict[str, object]:
    return {
        "period": "2026-06",
        "vendors": ["v1", "v2"],
        "customers": ["c1", "c2"],
        "employees": ["e1"],
    }


async def test_cycle_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/transactional/cycle/run", json=_cycle_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["collections"]["overdue"] == ["c2"]


async def test_cycle_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/transactional/cycle/run", json=_cycle_body())
    r2 = await client.post("/agents/transactional/cycle/run", json=_cycle_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_cycle_rejects_empty_vendors(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/transactional/cycle/run",
        json={"period": "2026-06", "vendors": [], "customers": ["c1"]},
    )
    assert resp.status_code == 422


async def test_payment_run_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post(
        "/agents/transactional/ap/run", json={"period": "2026-06", "vendors": ["v1", "v2"]}
    )
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    payments = [r for r in approvals if r["tool_name"] == "transactional_execute_payment"]
    assert len(payments) == 2  # default-deny holds both vendor payments

    decision = await client.post(
        f"/approvals/{payments[0]['id']}/approve", json={"approver": "treasurer-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # disbursement runs only post-approval


async def test_cycle_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/transactional/cycle/run", json=_cycle_body())).json()[
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
    assert {"billing", "accounts-receivable", "collections"} <= steps
