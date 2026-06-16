"""End-to-end tests for the shared platform API (health, approvals, jobs/SSE)."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from app.api.context import AppContext, build_context
from app.jobs import Job, ProgressEvent
from app.main import create_app


@pytest.fixture
def context() -> AppContext:
    return build_context()


@pytest.fixture
async def client(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(context)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_consequential_call_surfaces_in_approvals_then_executes(
    client: httpx.AsyncClient, context: AppContext
) -> None:
    # An agent proposes a consequential action; default-deny holds it.
    outcome = await context.guardrails.submit(
        context.connectors.get("kv_write"),
        {"key": "cash", "value": "swept"},
        actor="treasury",
        approver_role="treasurer",
        rationale="end-of-day sweep",
    )
    assert outcome.request is not None

    # It shows up in the approvals queue.
    listing = await client.get("/approvals")
    assert listing.status_code == 200
    rows = listing.json()
    assert any(r["id"] == outcome.request.id and r["state"] == "pending" for r in rows)

    # Approving it executes the held action.
    resp = await client.post(f"/approvals/{outcome.request.id}/approve", json={"approver": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["executed"] is True
    assert body["request"]["state"] == "approved"
    assert context.connectors.get("kv_read")
    # side effect applied
    store_val = await context.connectors.get("kv_read").invoke("cash")
    assert store_val == "swept"


async def test_reject_endpoint(client: httpx.AsyncClient, context: AppContext) -> None:
    outcome = await context.guardrails.submit(
        context.connectors.get("kv_write"),
        {"key": "cash", "value": "x"},
        actor="t",
        approver_role="treasurer",
    )
    assert outcome.request is not None
    resp = await client.post(
        f"/approvals/{outcome.request.id}/reject", json={"approver": "bob", "reason": "no"}
    )
    assert resp.status_code == 200
    assert resp.json()["request"]["state"] == "rejected"


async def test_approve_unknown_returns_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/approvals/ghost/approve", json={"approver": "x"})
    assert resp.status_code == 404


async def test_double_decision_returns_409(client: httpx.AsyncClient, context: AppContext) -> None:
    outcome = await context.guardrails.submit(
        context.connectors.get("kv_write"),
        {"key": "k", "value": "v"},
        actor="t",
        approver_role="r",
    )
    assert outcome.request is not None
    rid = outcome.request.id
    await client.post(f"/approvals/{rid}/approve", json={"approver": "x"})
    again = await client.post(f"/approvals/{rid}/approve", json={"approver": "x"})
    assert again.status_code == 409


async def test_job_status_and_sse_stream(client: httpx.AsyncClient, context: AppContext) -> None:
    async def worker(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        await emit(ProgressEvent(job_id=job.id, type="progress", payload={"done": 1, "total": 1}))
        return "result-value"

    context.jobs.register("demo", worker)
    job = await context.jobs.enqueue("demo", {})
    await context.jobs.drain()

    status = await client.get(f"/jobs/{job.id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["result"] == "result-value"

    # The SSE stream replays the job's events and then ends (job closed).
    async with client.stream("GET", f"/jobs/{job.id}/events") as resp:
        assert resp.status_code == 200
        body = await resp.aread()
    text = body.decode()
    assert "progress" in text
    assert '"done": 1' in text
    # terminal status event present
    assert "completed" in text
    # sanity: the payload is valid JSON in a data: line
    data_lines = [ln for ln in text.splitlines() if ln.startswith("data:")]
    assert data_lines
    json.loads(data_lines[0][len("data:") :].strip())


async def test_job_not_found_returns_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/jobs/nope")
    assert resp.status_code == 404


async def test_reject_unknown_returns_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/approvals/ghost/reject", json={"approver": "x", "reason": "n"})
    assert resp.status_code == 404
