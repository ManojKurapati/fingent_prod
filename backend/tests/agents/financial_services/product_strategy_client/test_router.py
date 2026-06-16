"""API-level tests for Product/Strategy/Client: the filing-gated, default-deny
launch and the KYC-gated, default-deny client activation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _store(**extra: str) -> FakeStore:
    data = {"pricing:cost": "100", "pricing:margin": "0.25"}
    data.update(extra)
    return FakeStore(data=data)


@pytest.fixture
def context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=_store(**{"filing:FT-1": "cleared"}))
    return ctx


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_initiative_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/product/initiatives", json={"name": "FX-Hedge", "filing_token": "FT-1"}
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["pricing"]["price"] == pytest.approx(125.0)


async def test_launch_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    await client.post(
        "/agents/product/initiatives", json={"name": "FX-Hedge", "filing_token": "FT-1"}
    )
    await context.jobs.drain()
    approvals = (await client.get("/approvals")).json()
    launch = [r for r in approvals if r["tool_name"] == "product_launch"]
    assert len(launch) == 1

    decision = await client.post(f"/approvals/{launch[0]['id']}/approve", json={"approver": "cpo"})
    assert decision.status_code == 200
    assert decision.json()["executed"] is True


async def test_launch_without_filing_never_creates_approval(context: AppContext) -> None:
    context.connectors = build_fake_connector(store=_store())  # no filing token cleared
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/agents/product/initiatives", json={"name": "FX-Hedge"})
        await context.jobs.drain()
        approvals = (await c.get("/approvals")).json()
    assert [r for r in approvals if r["tool_name"] == "product_launch"] == []


async def test_initiative_rejects_empty_name(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/product/initiatives", json={"name": ""})
    assert resp.status_code == 422


async def test_commercial_activation_blocked_until_approved(
    context: AppContext,
) -> None:
    context.connectors = build_fake_connector(store=_store(**{"kyc:KT-1": "cleared"}))
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/agents/product/commercial", json={"client_id": "C1", "kyc_token": "KT-1"}
        )
        assert resp.status_code == 200
        await context.jobs.drain()
        approvals = (await c.get("/approvals")).json()
        activate = [r for r in approvals if r["tool_name"] == "product_activate_client"]
        assert len(activate) == 1
        decision = await c.post(
            f"/approvals/{activate[0]['id']}/approve", json={"approver": "onboarding-lead"}
        )
        assert decision.json()["executed"] is True
