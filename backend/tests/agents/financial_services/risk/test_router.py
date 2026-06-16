"""API-level tests for Risk Management: the parallel risk run, breach escalation
held default-deny, and the synchronous gate endpoints other agents call.
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
        "var:trading": "80",
        "varlimit:trading": "100",
        "ecl:trading": "40",
        "ecllimit:trading": "50",
        "oploss:trading": "10",
        "oplosslimit:trading": "50",
        "lcr:trading": "1.2",
        "lcrmin:trading": "1.0",
        "modeldrift:trading": "0.05",
        "driftlimit:trading": "0.1",
        "exposure:trading": "100",
        "limit:trading": "1000",
    }
    data.update(overrides)
    return data


def _make_context(**overrides: str) -> AppContext:
    ctx = build_context()
    ctx.connectors = build_fake_connector(store=FakeStore(data=_data(**overrides)))
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


async def test_run_endpoint_enqueues_and_completes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    resp = await client.post("/agents/risk/run", json={"as_of": "2026-06-16", "book": "trading"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await context.jobs.drain()
    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["status"] == "completed"
    assert body["result"]["erm-aggregation"]["within_appetite"] is True


async def test_run_is_idempotent(client: httpx.AsyncClient) -> None:
    payload = {"as_of": "2026-06-16", "book": "trading"}
    r1 = await client.post("/agents/risk/run", json=payload)
    r2 = await client.post("/agents/risk/run", json=payload)
    assert r1.json()["job_id"] == r2.json()["job_id"]


async def test_breach_run_escalates_to_approvals_queue() -> None:
    context = _make_context(**{"var:trading": "150"})
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/agents/risk/run", json={"as_of": "2026-06-16", "book": "trading"})
        await context.jobs.drain()
        approvals = (await client.get("/approvals")).json()
        overrides = [r for r in approvals if r["tool_name"] == "risk_request_limit_override"]
        assert len(overrides) == 1


# --- synchronous gates (the mandatory pre-execution checks) ---------------


async def test_pre_trade_gate_passes(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/risk/gate/pre-trade", json={"book": "trading", "notional": 50.0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "PASS"
    assert body["token"] is not None


async def test_pre_trade_gate_denies_over_limit(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/risk/gate/pre-trade", json={"book": "trading", "notional": 5000.0}
    )
    assert resp.json()["decision"] == "DENY"
    assert resp.json()["token"] is None


async def test_pre_trade_gate_fail_closed_for_unknown_book(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/agents/risk/gate/pre-trade", json={"book": "unknown", "notional": 1.0}
    )
    assert resp.json()["decision"] == "DENY"


async def test_limit_check_gate(client: httpx.AsyncClient) -> None:
    resp = await client.post("/agents/risk/gate/limit-check", json={"book": "trading"})
    assert resp.json()["decision"] == "PASS"
