"""API-level tests for Wealth & Private Banking: enqueue -> worker -> status, the
KYC entry gate, and the suitability-/credit-gated consequential actions blocked
until approved. The router is auto-discovered, so ``create_app`` alone mounts it.
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
    ctx.connectors = build_fake_connector(
        store=FakeStore(
            data={
                "wealth:risk_tolerance:c1": "0.7",
                "wealth:collateral:c1": "1000",
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


async def test_clients_endpoint_runs_onboarding_and_plan(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/wealth-private-banking/clients",
        json={"client_id": "c1", "segment": "hnw", "name": "Ada"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["plan-reconciliation"]["reconciled"] is True


async def test_clients_endpoint_rejects_bad_segment(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/wealth-private-banking/clients",
        json={"client_id": "c1", "segment": "peasant", "name": "Ada"},
    )
    assert resp.status_code == 422


async def test_rebalance_held_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post(
        "/agents/wealth-private-banking/rebalance",
        json={"client_id": "c1", "proposed_risk": 0.5},
    )
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    moves = [r for r in approvals if r["tool_name"] == "wealth_rebalance"]
    assert len(moves) == 1  # default-deny holds the asset move

    decision = await client.post(
        f"/approvals/{moves[0]['id']}/approve", json={"approver": "advisor-jo"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_rebalance_unsuitable_books_nothing(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    # proposed risk far above tolerance -> suitability gate DENY -> no asset move proposed
    await client.post(
        "/agents/wealth-private-banking/rebalance",
        json={"client_id": "c1", "proposed_risk": 0.99},
    )
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "wealth_rebalance"] == []


async def test_credit_over_ltv_books_nothing(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post(
        "/agents/wealth-private-banking/credit",
        json={"client_id": "c1", "loan_amount": 900.0, "facility": "lombard"},
    )
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "wealth_extend_credit"] == []


async def test_credit_within_ltv_held_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post(
        "/agents/wealth-private-banking/credit",
        json={"client_id": "c1", "loan_amount": 400.0, "facility": "lombard"},
    )
    await context.jobs.drain()

    approvals = (await client.get("/approvals")).json()
    facilities = [r for r in approvals if r["tool_name"] == "wealth_extend_credit"]
    assert len(facilities) == 1

    decision = await client.post(
        f"/approvals/{facilities[0]['id']}/approve", json={"approver": "private-banker-le"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # facility books only post-approval
