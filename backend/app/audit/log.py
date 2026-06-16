"""Immutable, append-only audit log — FROZEN CONTRACT.

Every consequential decision in the platform — tool calls, LLM calls, subagent
inputs/outputs, and human approvals — is written here immutably with actor,
timestamp, and job lineage. This is the system of record for "who/what/why" and
feeds the Internal Audit agent. The log exposes no update or delete API.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A single immutable audit record."""

    id: str
    timestamp: datetime
    actor: str
    action: str
    payload: Mapping[str, Any]
    correlation_id: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryAuditLog:
    """Append-only audit log backed by an in-memory list.

    A real implementation persists to Postgres; the contract (record/events,
    append-only, immutable) is identical. Clock and id source are injectable so
    tests are deterministic.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._events: list[AuditEvent] = []

    async def record(
        self,
        *,
        actor: str,
        action: str,
        payload: Mapping[str, Any],
        correlation_id: str | None = None,
    ) -> AuditEvent:
        """Append an immutable event and return it. The payload is copied."""
        event = AuditEvent(
            id=self._id_factory(),
            timestamp=self._clock(),
            actor=actor,
            action=action,
            payload=MappingProxyType(dict(payload)),
            correlation_id=correlation_id,
        )
        self._events.append(event)
        return event

    async def events(self, *, correlation_id: str | None = None) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot, optionally filtered by lineage."""
        if correlation_id is None:
            return tuple(self._events)
        return tuple(e for e in self._events if e.correlation_id == correlation_id)
