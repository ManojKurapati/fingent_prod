"""API-level tests for Tax: enqueue -> worker -> status, SSE progress, and the
default-deny external-filing gate. The router is registered via auto-discovery,
so ``create_app`` alone mounts it.
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
                "income:US": "1000",
                "rate:US": "0.21",
                "income:UK": "500",
                "rate:UK": "0.25",
                "vat_out:US": "300",
                "vat_in:US": "120",
                "intercompany:US": "40",
                "foreign_tax:UK": "30",
                "dispute:US": "1",
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


def _provision_body() -> dict[str, object]:
    return {"period": "FY26", "jurisdictions": ["US", "UK"]}


async def test_provision_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/tax/provision", json=_provision_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["tax-provision"]["current"] == pytest.approx(335.0)


async def test_provision_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/tax/provision", json=_provision_body())
    r2 = await client.post("/agents/tax/provision", json=_provision_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_provision_rejects_empty_jurisdictions(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/tax/provision", json={"period": "FY26", "jurisdictions": []})
    assert resp.status_code == 422


async def test_filing_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/tax/file/ret-US-2026", json={"jurisdiction": "US"})
    assert resp.status_code == 200
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    filings = [r for r in approvals if r["tool_name"] == "tax_file_return"]
    assert len(filings) == 1  # default-deny holds the external submission

    decision = await client.post(
        f"/approvals/{filings[0]['id']}/approve", json={"approver": "head-of-tax-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # the filing runs only post-approval


async def test_provision_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/tax/provision", json=_provision_body())).json()["job_id"]

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
    assert {"direct-tax-compliance", "tax-provision"} <= steps
