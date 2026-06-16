"""API-level tests for Compliance: the screening run, the synchronous gate every
other agent calls, and the default-deny guardrail on SAR filing (external filing).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.connectors import FakeStore, build_fake_connector
from app.main import create_app


def _data(**overrides: str) -> dict[str, str]:
    data = {
        "kycrisk:cust1": "low",
        "sanctions:cust1": "0",
        "kycrisk:badco": "high",
        "sanctions:badco": "3",
        "incidents": "3",
        "filings": "2",
        "contracts": "5",
        "clearance:cust1": "clear",
        "clearance:badco": "blocked",
    }
    data.update(overrides)
    return data


def _make_context() -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=FakeStore(data=_data()))
    return ctx


@pytest.fixture
def context() -> AppContext:
    return _make_context()


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_screen_endpoint_clears_clean_subject(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/compliance/screen", json={"subject": "cust1"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["fraud-investigation"]["cleared"] is True


async def test_screen_endpoint_escalates_sanctioned_subject(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/compliance/screen", json={"subject": "badco"})
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["fraud-investigation"]["cleared"] is False
    assert result["fraud-investigation"]["sar_recommended"] is True


async def test_screen_is_idempotent(client: httpx.AsyncClient) -> None:
    r1 = await client.post("/agents/compliance/screen", json={"subject": "cust1"})
    r2 = await client.post("/agents/compliance/screen", json={"subject": "cust1"})
    assert r1.json()["job_id"] == r2.json()["job_id"]


# --- synchronous gate (PASS/HOLD/DENY) ------------------------------------


async def test_gate_check_pass(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/compliance/gate/check", json={"subject": "cust1", "action": "trade"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "PASS"
    assert body["token"] is not None


async def test_gate_check_deny_blocked(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/compliance/gate/check", json={"subject": "badco", "action": "trade"}
    )
    assert resp.json()["decision"] == "DENY"
    assert resp.json()["token"] is None


async def test_gate_check_fail_closed_unknown(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/compliance/gate/check", json={"subject": "ghost", "action": "trade"}
    )
    assert resp.json()["decision"] == "DENY"


# --- SAR filing is gated (default-deny) -----------------------------------


async def test_sar_filing_is_blocked_until_approved(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    body = {"subject": "badco", "narrative": "structuring pattern", "amount": 250_000.0}
    resp = await client.post("/agents/compliance/sar", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["executed"] is False  # default-deny: filing externally needs sign-off
    assert out["approval_id"] is not None

    sars = [
        r
        for r in (await client.get("/approvals")).json()
        if r["tool_name"] == "compliance_file_sar"
    ]
    assert len(sars) == 1
    assert sars[0]["approver_role"] == "mlro"

    decision = await client.post(
        f"/approvals/{out['approval_id']}/approve", json={"approver": "mlro-sam"}
    )
    assert decision.status_code == 200
    assert decision.json()["executed"] is True  # SAR files only post-approval


async def test_continuous_endpoint_runs_parallel(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/compliance/continuous", json={"scope": "firm"})
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    result = (await client.get(f"/jobs/{job_id}")).json()["result"]
    assert result["compliance-monitoring"]["open_incidents"] == 3
    assert result["regulatory-affairs"]["pending_filings"] == 2
    assert result["legal-counsel"]["contracts_under_review"] == 5
