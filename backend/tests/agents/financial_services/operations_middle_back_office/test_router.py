"""API-level tests for Operations: enqueue -> worker -> status, and the
default-deny guardrail on settlement instructions. Auto-discovered, so
``create_app`` alone mounts the router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _store(affirmed: bool = True) -> FakeStore:
    data = {
        "recon:internal": "100",
        "recon:external": "100",
        "nav:assets": "1000",
        "nav:liabilities": "200",
        "nav:shares": "100",
        "custody:holdings": "500",
        "custody:custodian": "500",
        "collateral:exposure": "300",
        "collateral:posted": "120",
    }
    if affirmed:
        data["trade:T1:affirmed"] = "yes"
    return FakeStore(data=data)


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=_store())
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _process_body(trade_id: str = "T1") -> dict[str, object]:
    return {"trade_id": trade_id, "amount": 1_000.0}


async def test_process_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/ops/process", json=_process_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["fund-accounting"]["nav"] == pytest.approx(8.0)


async def test_settlement_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/ops/process", json=_process_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    settlement = [r for r in approvals if r["tool_name"] == "ops_instruct_settlement"]
    assert len(settlement) == 1  # default-deny holds the instruction

    decision = await client.post(
        f"/approvals/{settlement[0]['id']}/approve", json={"approver": "ops-controller"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_unconfirmed_trade_never_creates_an_approval(
    context: AppContext,
) -> None:
    context.connectors = build_fake_connector(store=_store(affirmed=False))
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/agents/ops/process", json=_process_body())
        await context.jobs.drain()
        approvals = (await c.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "ops_instruct_settlement"] == []


async def test_process_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/ops/process", json=_process_body())
    r2 = await client.post("/agents/ops/process", json=_process_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_process_rejects_empty_trade_id(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/ops/process", json={"trade_id": "", "amount": 1.0})
    assert resp.status_code == 422


async def test_recon_endpoint_runs(client: httpx.AsyncClient, context: AppContext) -> None:
    resp = await client.post("/agents/ops/recon", json={"as_of": "2026-06-16"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["collateral-mgmt"]["margin_call"] == pytest.approx(180.0)
