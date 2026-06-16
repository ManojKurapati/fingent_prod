"""API-level tests for Internal Audit & Controls: enqueue -> worker -> status,
SSE progress, and the default-deny guardrail on report issuance. The router is
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
                "evidence:c1": "fail",  # c1 is a control deficiency
                "evidence:c2": "pass",
                "sox:c1": "effective",
                "sox:c2": "deficient",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # audit router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _body() -> dict[str, object]:
    return {"engagement": "FY26-rev", "controls": ["c1", "c2"]}


async def test_engagement_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/audit/engagement", json=_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert sorted(body["result"]["findings-reporting"]["findings"]) == ["c1", "c2"]
    assert body["result"]["remediation-tracking"]["open"] == 2


async def test_engagement_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/audit/engagement", json=_body())
    r2 = await client.post("/agents/audit/engagement", json=_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_engagement_rejects_empty_controls(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/audit/engagement", json={"engagement": "x", "controls": []})
    assert resp.status_code == 422


async def test_report_publish_is_blocked_until_cae_approves(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/audit/engagement", json=_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    publish = [r for r in approvals if r["tool_name"] == "audit_publish_findings"]
    assert len(publish) == 1  # default-deny holds the report issuance

    decision = await client.post(
        f"/approvals/{publish[0]['id']}/approve", json={"approver": "cae-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # report issues only post-approval


async def test_engagement_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/audit/engagement", json=_body())).json()["job_id"]

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
    assert {"audit-planning", "findings-reporting", "remediation-tracking"} <= steps
