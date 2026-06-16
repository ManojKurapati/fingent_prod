"""Tests for the immutable, append-only audit log."""

import dataclasses
from datetime import UTC, datetime

import pytest
from app.audit import AuditEvent, InMemoryAuditLog


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def test_record_returns_event_with_metadata() -> None:
    log = InMemoryAuditLog(clock=_fixed_clock, id_factory=iter(["e1", "e2"]).__next__)
    ev = await log.record(actor="controller", action="tool_call", payload={"tool": "kv_write"})

    assert isinstance(ev, AuditEvent)
    assert ev.id == "e1"
    assert ev.actor == "controller"
    assert ev.action == "tool_call"
    assert ev.payload == {"tool": "kv_write"}
    assert ev.timestamp == _fixed_clock()


async def test_events_returned_in_append_order() -> None:
    log = InMemoryAuditLog(id_factory=iter(["a", "b", "c"]).__next__)
    await log.record(actor="x", action="one", payload={})
    await log.record(actor="x", action="two", payload={})
    await log.record(actor="x", action="three", payload={})

    assert [e.action for e in await log.events()] == ["one", "two", "three"]


async def test_events_snapshot_is_immutable_tuple() -> None:
    log = InMemoryAuditLog()
    await log.record(actor="x", action="one", payload={})
    events = await log.events()
    assert isinstance(events, tuple)


async def test_audit_event_is_frozen() -> None:
    log = InMemoryAuditLog()
    ev = await log.record(actor="x", action="one", payload={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.actor = "tampered"  # type: ignore[misc]


async def test_payload_is_copied_so_caller_mutation_does_not_leak() -> None:
    log = InMemoryAuditLog()
    payload = {"amount": 100}
    await log.record(actor="x", action="pay", payload=payload)
    payload["amount"] = 999  # mutate caller's dict after recording

    (stored,) = await log.events()
    assert stored.payload == {"amount": 100}


async def test_filter_by_correlation_id() -> None:
    log = InMemoryAuditLog(id_factory=iter(["1", "2", "3"]).__next__)
    await log.record(actor="x", action="a", payload={}, correlation_id="job-1")
    await log.record(actor="x", action="b", payload={}, correlation_id="job-2")
    await log.record(actor="x", action="c", payload={}, correlation_id="job-1")

    chain = await log.events(correlation_id="job-1")
    assert [e.action for e in chain] == ["a", "c"]
