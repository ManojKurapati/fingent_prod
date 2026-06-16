"""API-level tests for Quant/Data/Tech: research fan-out enqueue, and the
validation-gated, default-deny promotion of a model to production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=FakeStore(data={"validation:VT-1": "approved"}))
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_jobs_endpoint_runs_research_fanout(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/quant/jobs", json={"dataset": "eod-prices"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["systematic-dev"]["candidate"] is True


async def test_jobs_rejects_empty_dataset(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/quant/jobs", json={"dataset": ""})
    assert resp.status_code == 422


async def test_promote_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/quant/promote", json={"model_id": "M1", "validation_token": "VT-1"}
    )
    assert resp.status_code == 200
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    promote = [r for r in approvals if r["tool_name"] == "quant_promote_model"]
    assert len(promote) == 1  # validation cleared, but default-deny still holds it

    decision = await client.post(
        f"/approvals/{promote[0]['id']}/approve", json={"approver": "head-of-quant"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_promote_without_validation_token_never_creates_approval(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/quant/promote", json={"model_id": "M1"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["promote"]["blocked"] is True
    approvals = (await client.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "quant_promote_model"] == []
