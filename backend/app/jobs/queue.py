"""Async job queue abstraction — FROZEN CONTRACT.

Endpoints enqueue work and return a ``job_id`` immediately; workers run the
orchestrator's plan in the background. The queue guarantees:

* **Idempotency** — enqueuing with the same ``idempotency_key`` returns the
  existing job and never double-executes (no double-posting to ledgers / double
  trades).
* **Retries** — a handler that raises is retried up to ``max_attempts``; only
  then is the job marked ``FAILED``.

``InMemoryJobQueue`` is the test/dev fake. A production queue (arq/Redis) wraps
the same :class:`JobQueue` interface.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.jobs.progress import ProgressBus, ProgressEvent


class JobStatus(StrEnum):
    """Lifecycle of a job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """A unit of background work."""

    id: str
    kind: str
    payload: Any
    status: JobStatus = JobStatus.QUEUED
    idempotency_key: str | None = None
    max_attempts: int = 3
    attempts: int = 0
    result: Any | None = None
    error: str | None = None
    correlation_id: str | None = None


# A progress emitter handed to handlers.
Emit = Callable[[ProgressEvent], Awaitable[None]]
# A job handler: (job, emit) -> result.
JobHandler = Callable[[Job, Emit], Awaitable[Any]]


class JobQueue(ABC):
    """The interface every queue implementation (fake or real) must satisfy."""

    @abstractmethod
    def register(self, kind: str, handler: JobHandler) -> None: ...

    @abstractmethod
    async def enqueue(
        self,
        kind: str,
        payload: Any,
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        correlation_id: str | None = None,
    ) -> Job: ...

    @abstractmethod
    def get(self, job_id: str) -> Job: ...

    @abstractmethod
    async def drain(self) -> None: ...


@dataclass
class InMemoryJobQueue(JobQueue):
    """A deterministic in-process queue for tests and local development."""

    id_factory: Callable[[], str] = field(default_factory=lambda: lambda: uuid.uuid4().hex)
    progress: ProgressBus = field(default_factory=ProgressBus)

    def __post_init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._pending: deque[str] = deque()

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    async def enqueue(
        self,
        kind: str,
        payload: Any,
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        correlation_id: str | None = None,
    ) -> Job:
        if kind not in self._handlers:
            raise KeyError(f"no handler registered for job kind {kind!r}")
        if idempotency_key is not None and idempotency_key in self._by_key:
            return self._jobs[self._by_key[idempotency_key]]

        job = Job(
            id=self.id_factory(),
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            correlation_id=correlation_id,
        )
        self._jobs[job.id] = job
        if idempotency_key is not None:
            self._by_key[idempotency_key] = job.id
        self._pending.append(job.id)
        return job

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    async def drain(self) -> None:
        """Run queued jobs to a terminal state, re-queuing retryable failures."""
        while self._pending:
            job = self._jobs[self._pending.popleft()]
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                continue
            await self._run_once(job)

    async def _run_once(self, job: Job) -> None:
        handler = self._handlers[job.kind]
        job.status = JobStatus.RUNNING
        job.attempts += 1

        async def _emit(event: ProgressEvent) -> None:
            await self.progress.publish(event)

        try:
            job.result = await handler(job, _emit)
        except Exception as exc:
            if job.attempts < job.max_attempts:
                job.status = JobStatus.QUEUED
                self._pending.append(job.id)
                return
            job.status = JobStatus.FAILED
            job.error = str(exc)
            await self._finish(job)
            return
        job.status = JobStatus.COMPLETED
        await self._finish(job)

    async def _finish(self, job: Job) -> None:
        """Emit a terminal status event and close the job's progress stream."""
        await self.progress.publish(
            ProgressEvent(job_id=job.id, type="status", payload={"state": job.status.value})
        )
        await self.progress.close(job.id)
