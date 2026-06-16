"""Per-job progress streaming — FROZEN CONTRACT.

A :class:`ProgressBus` fans out :class:`ProgressEvent`s to live SSE subscribers
and keeps a replayable history per job. Handlers publish lifecycle/progress
events; the React client subscribes over ``GET /jobs/{job_id}/events``.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One streamed progress event for a job."""

    job_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


# Sentinel pushed onto subscriber queues to end a stream.
_CLOSE = object()


class ProgressBus:
    """In-memory pub/sub for job progress with per-job replayable history."""

    def __init__(self) -> None:
        self._history: dict[str, list[ProgressEvent]] = defaultdict(list)
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)
        self._closed: set[str] = set()

    async def publish(self, event: ProgressEvent) -> None:
        """Record ``event`` and push it to every live subscriber for its job."""
        self._history[event.job_id].append(event)
        for queue in self._subscribers.get(event.job_id, []):
            await queue.put(event)

    async def close(self, job_id: str) -> None:
        """Signal end-of-stream so subscribers' iterators complete."""
        self._closed.add(job_id)
        for queue in self._subscribers.get(job_id, []):
            await queue.put(_CLOSE)

    def history(self, job_id: str) -> list[ProgressEvent]:
        """All events published for ``job_id`` so far (for replay/audit/tests)."""
        return list(self._history.get(job_id, []))

    async def subscribe(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Yield events for ``job_id``: replay history, then stream live until close.

        History is snapshotted and the live queue attached atomically (no awaits
        between), so subscribers see every event exactly once. A subscriber to an
        already-closed job replays history and then completes.
        """
        backlog = list(self._history.get(job_id, []))
        already_closed = job_id in self._closed
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers[job_id].append(queue)
        try:
            for event in backlog:
                yield event
            if already_closed:
                return
            while True:
                item = await queue.get()
                if item is _CLOSE:
                    return
                yield item
        finally:
            self._subscribers[job_id].remove(queue)


def format_sse(event: ProgressEvent) -> dict[str, str]:
    """Render an event as an sse-starlette ``ServerSentEvent`` kwargs dict."""
    data = json.dumps({"job_id": event.job_id, "type": event.type, "payload": event.payload})
    return {"event": event.type, "data": data}
