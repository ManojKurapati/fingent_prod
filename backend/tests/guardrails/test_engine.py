"""Tests for the guardrail / approval engine (default-deny on consequential calls)."""

from typing import NamedTuple

import pytest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import (
    ApprovalNotFoundError,
    ApprovalState,
    GuardrailEngine,
    InvalidTransitionError,
)


class Ctx(NamedTuple):
    engine: GuardrailEngine
    store: FakeStore
    audit: InMemoryAuditLog
    connector: ToolRegistry


def _ctx() -> Ctx:
    store = FakeStore()
    connector = build_fake_connector(store=store)
    audit = InMemoryAuditLog()
    engine = GuardrailEngine(
        audit=audit, id_factory=iter([f"req-{i}" for i in range(100)]).__next__
    )
    return Ctx(engine=engine, store=store, audit=audit, connector=connector)


async def test_non_consequential_tool_runs_immediately() -> None:
    c = _ctx()
    c.store.data["k"] = "v"
    outcome = await c.engine.submit(
        c.connector.get("kv_read"), "k", actor="fpa", approver_role="controller"
    )
    assert outcome.executed is True
    assert outcome.output == "v"
    assert outcome.request is None
    assert any(e.action == "tool_call" for e in await c.audit.events())


async def test_consequential_tool_is_blocked_until_approved() -> None:
    c = _ctx()
    outcome = await c.engine.submit(
        c.connector.get("kv_write"),
        {"key": "cash", "value": "moved"},
        actor="treasury",
        approver_role="treasurer",
        rationale="sweep idle balance",
    )
    # DEFAULT-DENY: not executed, an approval request is created instead
    assert outcome.executed is False
    assert outcome.request is not None
    assert outcome.request.state is ApprovalState.PENDING
    assert outcome.request.approver_role == "treasurer"
    # the consequential side effect did NOT happen
    assert "cash" not in c.store.data
    assert any(e.action == "approval.requested" for e in await c.audit.events())


async def test_approval_executes_the_held_action() -> None:
    c = _ctx()
    outcome = await c.engine.submit(
        c.connector.get("kv_write"),
        {"key": "cash", "value": "moved"},
        actor="treasury",
        approver_role="treasurer",
    )
    assert outcome.request is not None
    result = await c.engine.approve(outcome.request.id, approver="alice")

    assert result.executed is True
    assert c.store.data["cash"] == "moved"  # side effect applied only after approval
    assert result.request is not None
    assert result.request.state is ApprovalState.APPROVED
    assert result.request.decided_by == "alice"
    actions = [e.action for e in await c.audit.events()]
    assert "approval.requested" in actions
    assert "approval.granted" in actions
    assert "tool_call" in actions


async def test_rejection_never_executes() -> None:
    c = _ctx()
    outcome = await c.engine.submit(
        c.connector.get("kv_write"),
        {"key": "cash", "value": "moved"},
        actor="treasury",
        approver_role="treasurer",
    )
    assert outcome.request is not None
    result = await c.engine.reject(outcome.request.id, approver="bob", reason="over limit")

    assert result.executed is False
    assert "cash" not in c.store.data
    assert result.request is not None
    assert result.request.state is ApprovalState.REJECTED
    assert any(e.action == "approval.rejected" for e in await c.audit.events())


async def test_pending_lists_only_open_requests() -> None:
    c = _ctx()
    o1 = await c.engine.submit(
        c.connector.get("kv_write"), {"key": "a", "value": "1"}, actor="x", approver_role="r"
    )
    await c.engine.submit(
        c.connector.get("kv_write"), {"key": "b", "value": "2"}, actor="x", approver_role="r"
    )
    assert len(c.engine.pending()) == 2

    assert o1.request is not None
    await c.engine.approve(o1.request.id, approver="z")
    assert len(c.engine.pending()) == 1


async def test_approving_unknown_request_raises() -> None:
    c = _ctx()
    with pytest.raises(ApprovalNotFoundError):
        await c.engine.approve("ghost", approver="z")


async def test_get_returns_pending_and_decided_requests() -> None:
    c = _ctx()
    outcome = await c.engine.submit(
        c.connector.get("kv_write"), {"key": "a", "value": "1"}, actor="x", approver_role="r"
    )
    assert outcome.request is not None
    req_id = outcome.request.id
    assert c.engine.get(req_id).state is ApprovalState.PENDING

    await c.engine.approve(req_id, approver="z")
    assert c.engine.get(req_id).state is ApprovalState.APPROVED

    with pytest.raises(ApprovalNotFoundError):
        c.engine.get("nope")


async def test_cannot_decide_twice() -> None:
    c = _ctx()
    outcome = await c.engine.submit(
        c.connector.get("kv_write"), {"key": "a", "value": "1"}, actor="x", approver_role="r"
    )
    assert outcome.request is not None
    req_id = outcome.request.id
    await c.engine.approve(req_id, approver="z")
    with pytest.raises(InvalidTransitionError):
        await c.engine.approve(req_id, approver="z")
    with pytest.raises(InvalidTransitionError):
        await c.engine.reject(req_id, approver="z", reason="late")
