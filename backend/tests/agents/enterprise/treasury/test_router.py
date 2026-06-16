"""API-level tests for Treasury.

* ``POST /agents/treasury/daily-position`` enqueues the hybrid morning sequence,
  streams step progress over SSE, and yields a dashboard payload.
* ``POST /agents/treasury/hedge/execute`` and ``POST /agents/treasury/sweep`` are
  gated cash-movement endpoints: default-deny holds them until a Treasurer
  approves, after which the held action executes.
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
                "balance:a1": "1000",
                "bank:a1": "1000",
                "ar": "400",
                "ap": "150",
                "fx:EUR": "300",
                "debt": "2000",
                "ebitda": "1000",
                "active_banks": "2",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # treasury router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _position_body() -> dict[str, object]:
    return {"as_of": "2026-06-16", "accounts": ["a1"]}


async def test_daily_position_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/treasury/daily-position", json=_position_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["liquidity-forecasting"]["forecast"] == pytest.approx(1250.0)


async def test_daily_position_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/treasury/daily-position", json=_position_body())
    r2 = await client.post("/agents/treasury/daily-position", json=_position_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_daily_position_rejects_empty_accounts(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/treasury/daily-position", json={"as_of": "2026-06-16", "accounts": []}
    )
    assert resp.status_code == 422


async def test_daily_position_streams_step_progress(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/treasury/daily-position", json=_position_body())).json()[
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
    assert {"cash-positioning", "liquidity-forecasting", "fx-hedging", "debt-covenants"} <= steps


# --- gated cash-movement endpoints ----------------------------------------


async def test_hedge_execute_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/treasury/hedge/execute",
        json={"pair": "EURUSD", "notional": 500.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["executed"] is False  # default-deny
    assert body["approval_id"] is not None

    approvals = (await client.get("/approvals")).json()
    hedges = [r for r in approvals if r["tool_name"] == "treasury_execute_hedge"]
    assert len(hedges) == 1
    assert hedges[0]["approver_role"] == "treasurer"

    decision = await client.post(
        f"/approvals/{body['approval_id']}/approve", json={"approver": "treasurer-lee"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # hedge fires only post-approval


async def test_sweep_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/treasury/sweep",
        json={"from_account": "a1", "to_account": "a2", "amount": 250.0},
    )
    body = resp.json()
    assert body["executed"] is False

    approvals = (await client.get("/approvals")).json()
    sweeps = [r for r in approvals if r["tool_name"] == "treasury_execute_sweep"]
    assert len(sweeps) == 1

    decision = await client.post(
        f"/approvals/{body['approval_id']}/approve", json={"approver": "treasurer-lee"}
    )
    assert decision.json()["executed"] is True
