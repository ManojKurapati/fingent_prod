"""Tests for the in-memory job queue: idempotency, retries, no double-execution."""

import pytest
from app.jobs import InMemoryJobQueue, Job, JobStatus, ProgressEvent


async def test_enqueue_creates_queued_job() -> None:
    q = InMemoryJobQueue(id_factory=iter(["j1"]).__next__)
    q.register("noop", _ok_handler)
    job = await q.enqueue("noop", {"x": 1})
    assert isinstance(job, Job)
    assert job.id == "j1"
    assert job.status is JobStatus.QUEUED
    assert job.payload == {"x": 1}


async def test_run_executes_handler_and_completes() -> None:
    q = InMemoryJobQueue()
    q.register("echo", _echo_handler)
    job = await q.enqueue("echo", "hi")
    await q.drain()
    done = q.get(job.id)
    assert done.status is JobStatus.COMPLETED
    assert done.result == "echo:hi"
    assert done.attempts == 1


async def test_idempotency_key_dedupes_enqueue_and_runs_once() -> None:
    runs = {"n": 0}

    async def counting(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        runs["n"] += 1
        return "ok"

    q = InMemoryJobQueue()
    q.register("once", counting)
    a = await q.enqueue("once", {}, idempotency_key="k1")
    b = await q.enqueue("once", {}, idempotency_key="k1")
    assert a.id == b.id  # same job returned, not a second enqueue

    await q.drain()
    assert runs["n"] == 1  # executed exactly once — no double-posting


async def test_retries_until_success() -> None:
    attempts = {"n": 0}

    async def flaky(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    q = InMemoryJobQueue()
    q.register("flaky", flaky)
    job = await q.enqueue("flaky", {}, max_attempts=3)
    await q.drain()
    done = q.get(job.id)
    assert done.status is JobStatus.COMPLETED
    assert done.result == "recovered"
    assert done.attempts == 3


async def test_fails_after_exhausting_retries() -> None:
    async def always_fail(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    q = InMemoryJobQueue()
    q.register("bad", always_fail)
    job = await q.enqueue("bad", {}, max_attempts=2)
    await q.drain()
    done = q.get(job.id)
    assert done.status is JobStatus.FAILED
    assert done.attempts == 2
    assert "down" in (done.error or "")


async def test_completed_job_is_not_re_executed_on_second_drain() -> None:
    runs = {"n": 0}

    async def counting(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        runs["n"] += 1
        return "ok"

    q = InMemoryJobQueue()
    q.register("once", counting)
    await q.enqueue("once", {})
    await q.drain()
    await q.drain()  # nothing queued — must not re-run
    assert runs["n"] == 1


async def test_enqueue_unknown_kind_raises() -> None:
    q = InMemoryJobQueue()
    with pytest.raises(KeyError):
        await q.enqueue("missing", {})


async def test_handler_can_emit_progress_to_bus() -> None:
    async def worker(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
        await emit(ProgressEvent(job_id=job.id, type="progress", payload={"done": 1, "total": 2}))
        await emit(ProgressEvent(job_id=job.id, type="progress", payload={"done": 2, "total": 2}))
        return "done"

    q = InMemoryJobQueue()
    q.register("work", worker)
    job = await q.enqueue("work", {})
    await q.drain()

    events = [e for e in q.progress.history(job.id) if e.type == "progress"]
    assert [e.payload["done"] for e in events] == [1, 2]
    # a terminal status event is also emitted and the stream is closed
    assert any(
        e.type == "status" and e.payload["state"] == "completed" for e in q.progress.history(job.id)
    )


async def _ok_handler(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
    return "ok"


async def _echo_handler(job: Job, emit) -> str:  # type: ignore[no-untyped-def]
    return f"echo:{job.payload}"
