"""API-level tests for Insurance: enqueue -> worker -> status, and the mandatory
accumulation gate + default-deny guardrail on policy binding.

The router is registered via auto-discovery, so ``create_app`` alone mounts it.
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
                "rate:US-FL": "0.03",
                "catfactor:hurricane": "0.1",
                "accumulation:US-FL:hurricane": "100000",
                "limit:US-FL:hurricane": "500000",
                "grossexposure:US-FL": "1000000",
                "retention:US-FL": "400000",
                "combinedratio:homeowners": "0.92",
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


def _submission_body() -> dict[str, object]:
    return {"submission_id": "S1", "region": "US-FL", "peril": "hurricane", "tiv": 1_000_000.0}


async def test_submission_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/insurance/submissions", json=_submission_body())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    await context.jobs.drain()

    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["underwriting"]["within_appetite"] is True


async def test_submission_is_idempotent_on_repeat(client: httpx.AsyncClient) -> None:
    r1 = await client.post("/agents/insurance/submissions", json=_submission_body())
    r2 = await client.post("/agents/insurance/submissions", json=_submission_body())
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_submission_rejects_nonpositive_tiv(client: httpx.AsyncClient) -> None:
    bad = {"submission_id": "S1", "region": "US-FL", "peril": "hurricane", "tiv": 0.0}
    resp = await client.post("/agents/insurance/submissions", json=bad)
    assert resp.status_code == 422


async def test_bind_within_appetite_is_held_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    body = {
        "submission_id": "S1",
        "region": "US-FL",
        "peril": "hurricane",
        "pml": 100_000.0,
        "premium": 30_000.0,
    }
    resp = await client.post("/agents/insurance/submissions/bind", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["gate"] == "PASS"
    assert out["executed"] is False  # default-deny: held for human approval
    assert out["approval_id"] is not None

    binds = [
        r
        for r in (await client.get("/approvals")).json()
        if r["tool_name"] == "insurance_bind_policy"
    ]
    assert len(binds) == 1

    decision = await client.post(
        f"/approvals/{out['approval_id']}/approve", json={"approver": "chief-underwriter"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # bind fires only post-approval


async def test_bind_blocked_when_accumulation_gate_denies(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    # pml pushes proposed accumulation (100k + 450k) over the 500k appetite limit.
    body = {
        "submission_id": "S1",
        "region": "US-FL",
        "peril": "hurricane",
        "pml": 450_000.0,
        "premium": 30_000.0,
    }
    resp = await client.post("/agents/insurance/submissions/bind", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["gate"] == "DENY"
    assert out["executed"] is False
    assert out["approval_id"] is None  # the risk gate fails BEFORE any approval is raised
    # nothing was even submitted to the guardrail engine
    assert context.guardrails.pending() == []


async def test_portfolio_endpoint_runs_parallel(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post(
        "/agents/insurance/portfolio", json={"region": "US-FL", "product": "homeowners"}
    )
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["reinsurance"]["ceded"] == pytest.approx(600_000.0)
    assert result["product"]["profitable"] is True


async def test_claims_endpoint_runs(client: httpx.AsyncClient, context: AppContext) -> None:
    resp = await client.post(
        "/agents/insurance/claims", json={"claim_id": "CLM1", "amount": 50_000.0}
    )
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["claims"]["reserve"] == pytest.approx(50_000.0)
