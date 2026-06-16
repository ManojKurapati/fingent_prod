"""Guardrail / approval engine — FROZEN CONTRACT.

Intercepts any **consequential** tool call and routes it to a human approval
queue before execution. The policy is **default-deny**: a consequential action
never runs until an approval record exists and is explicitly granted. Every
decision — request, grant, reject — is written immutably to the audit log.

Non-consequential tools pass straight through (and are still audited).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.audit import InMemoryAuditLog
from app.connectors import Tool


class ApprovalState(StrEnum):
    """Lifecycle of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalRequest:
    """A human-in-the-loop approval request for a consequential action."""

    id: str
    tool_name: str
    actor: str
    approver_role: str
    rationale: str
    correlation_id: str | None
    created_at: datetime
    evidence: dict[str, Any] = field(default_factory=dict)
    state: ApprovalState = ApprovalState.PENDING
    decided_at: datetime | None = None
    decided_by: str | None = None
    reject_reason: str | None = None


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """Result of submitting a tool call or deciding on a request."""

    executed: bool
    output: Any | None
    request: ApprovalRequest | None


class ApprovalNotFoundError(KeyError):
    """Raised when an approval request id is unknown."""


class InvalidTransitionError(RuntimeError):
    """Raised when approving/rejecting a request that is already decided."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Held:
    request: ApprovalRequest
    tool: Tool[Any, Any]
    payload: Any


class GuardrailEngine:
    """The single, shared choke point between an AI proposal and a real effect."""

    def __init__(
        self,
        *,
        audit: InMemoryAuditLog,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._audit = audit
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._held: dict[str, _Held] = {}
        self._decided: dict[str, ApprovalRequest] = {}

    async def submit(
        self,
        tool: Tool[Any, Any],
        payload: Any,
        *,
        actor: str,
        approver_role: str,
        rationale: str = "",
        evidence: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> GateOutcome:
        """Run a non-consequential tool now; gate a consequential one for approval."""
        if not tool.consequential:
            output = await tool.invoke(payload)
            await self._audit.record(
                actor=actor,
                action="tool_call",
                payload={"tool": tool.name, "gated": False},
                correlation_id=correlation_id,
            )
            return GateOutcome(executed=True, output=output, request=None)

        request = ApprovalRequest(
            id=self._id_factory(),
            tool_name=tool.name,
            actor=actor,
            approver_role=approver_role,
            rationale=rationale,
            correlation_id=correlation_id,
            created_at=self._clock(),
            evidence=dict(evidence or {}),
        )
        self._held[request.id] = _Held(request=request, tool=tool, payload=payload)
        await self._audit.record(
            actor=actor,
            action="approval.requested",
            payload={"request_id": request.id, "tool": tool.name, "approver_role": approver_role},
            correlation_id=correlation_id,
        )
        return GateOutcome(executed=False, output=None, request=request)

    async def approve(self, request_id: str, *, approver: str) -> GateOutcome:
        """Grant approval and execute the held action."""
        held = self._take_pending(request_id)
        req = held.request
        req.state = ApprovalState.APPROVED
        req.decided_at = self._clock()
        req.decided_by = approver

        output = await held.tool.invoke(held.payload)
        await self._audit.record(
            actor=approver,
            action="approval.granted",
            payload={"request_id": req.id, "tool": req.tool_name},
            correlation_id=req.correlation_id,
        )
        await self._audit.record(
            actor=req.actor,
            action="tool_call",
            payload={"tool": req.tool_name, "gated": True, "request_id": req.id},
            correlation_id=req.correlation_id,
        )
        return GateOutcome(executed=True, output=output, request=req)

    async def reject(self, request_id: str, *, approver: str, reason: str = "") -> GateOutcome:
        """Reject the request; the held action never executes."""
        held = self._take_pending(request_id)
        req = held.request
        req.state = ApprovalState.REJECTED
        req.decided_at = self._clock()
        req.decided_by = approver
        req.reject_reason = reason
        await self._audit.record(
            actor=approver,
            action="approval.rejected",
            payload={"request_id": req.id, "tool": req.tool_name, "reason": reason},
            correlation_id=req.correlation_id,
        )
        return GateOutcome(executed=False, output=None, request=req)

    def get(self, request_id: str) -> ApprovalRequest:
        """Fetch a request (pending or decided) by id."""
        if request_id in self._held:
            return self._held[request_id].request
        if request_id in self._decided:
            return self._decided[request_id]
        raise ApprovalNotFoundError(request_id)

    def pending(self) -> list[ApprovalRequest]:
        """All currently-open approval requests."""
        return [h.request for h in self._held.values()]

    def _take_pending(self, request_id: str) -> _Held:
        held = self._held.get(request_id)
        if held is None:
            if request_id in self._decided:
                raise InvalidTransitionError(f"request {request_id!r} is already decided")
            raise ApprovalNotFoundError(request_id)
        del self._held[request_id]
        self._decided[request_id] = held.request
        return held
