"""API-level tests for Leadership: enqueue -> worker -> status, SSE progress, and
the default-deny guardrail on board-pack publication. The router is registered via
auto-discovery (no shared-registry edits), so ``create_app`` alone mounts it.
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
                "pnl:emea": "100",
                "pnl:amer": "150",
                "capital:debt": "60",
                "capital:equity": "40",
                "budget:plan": "200",
                "initiatives:count": "3",
            }
        )
    )
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)  # leadership router is auto-discovered
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _board_body() -> dict[str, object]:
    return {"period": "FY26", "divisions": ["emea", "amer"], "target_leverage": 0.4}


async def test_board_pack_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/leadership/board-pack", json=_board_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["board-investor-reporting"]["pack"]["group_pnl"] == 250.0


async def test_board_pack_is_idempotent_on_repeat(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    r1 = await client.post("/agents/leadership/board-pack", json=_board_body())
    r2 = await client.post("/agents/leadership/board-pack", json=_board_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_board_pack_rejects_empty_divisions(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/leadership/board-pack", json={"period": "FY26", "divisions": []}
    )
    assert resp.status_code == 422


async def test_board_pack_publish_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post("/agents/leadership/board-pack", json=_board_body())
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    publish = [r for r in approvals if r["tool_name"] == "leadership_publish_board_pack"]
    assert len(publish) == 1  # default-deny holds the external publication

    decision = await client.post(
        f"/approvals/{publish[0]['id']}/approve", json={"approver": "cfo-sam"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # publication runs only post-approval


async def test_board_pack_streams_step_progress_events(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    job_id = (await client.post("/agents/leadership/board-pack", json=_board_body())).json()[
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
    assert {"divisional-rollup", "capital-strategy", "board-investor-reporting"} <= steps


async def test_capital_scenario_endpoint_runs_sequentially(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/leadership/capital-scenario",
        json={"period": "FY26", "divisions": ["emea", "amer"], "target_leverage": 0.7},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["capital-strategy"]["leverage"] == pytest.approx(0.6)
    assert result["capital-strategy"]["recommendation"] == "raise_debt"
