"""API-level tests for Retail & Commercial Banking: enqueue -> worker -> status,
SSE stage progression, and the credit-gated disbursement blocked until an
underwriter approves. The router is auto-discovered, so ``create_app`` mounts it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _approve_store() -> dict[str, str]:
    return {"bank:income:a1": "100", "bank:debt_service:a1": "20", "bank:collateral:a1": "200"}


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=FakeStore(data=_approve_store()))
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body(channel: str = "personal") -> dict[str, object]:
    return {"application_id": "a1", "channel": channel, "applicant": "ann", "loan_amount": 100.0}


async def test_application_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/retail-commercial-banking/applications", json=_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["underwriting"]["decision"] == "approve"


async def test_application_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/retail-commercial-banking/applications", json=_body())
    r2 = await client.post("/agents/retail-commercial-banking/applications", json=_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_application_rejects_unknown_channel(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/retail-commercial-banking/applications", json=_body("carrier-pigeon")
    )
    assert resp.status_code == 422


async def test_disbursement_blocked_until_underwriter_approves(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/retail-commercial-banking/applications", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    loans = [r for r in approvals if r["tool_name"] == "banking_fund_loan"]
    assert len(loans) == 1  # default-deny holds the disbursement

    decision = await client.post(
        f"/approvals/{loans[0]['id']}/approve", json={"approver": "underwriter-sam"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # funds only after sign-off


async def test_declined_application_funds_nothing(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    context.connectors = build_fake_connector(
        store=FakeStore(
            data={
                "bank:income:a1": "100",
                "bank:debt_service:a1": "70",
                "bank:collateral:a1": "500",
            }
        )
    )
    await client.post("/agents/retail-commercial-banking/applications", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "banking_fund_loan"] == []


async def test_application_streams_stage_progress(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (
        await client.post("/agents/retail-commercial-banking/applications", json=_body())
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
    assert {"loan-origination", "credit-analysis", "underwriting", "loan-funding"} <= steps
