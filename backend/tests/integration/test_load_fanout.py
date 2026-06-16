"""Load test (wave 4, task 5): bounded concurrency + no double-execution on retry.

Models the FP&A-style "variance across many cost centres" fan-out. Asserts the
fan-out never exceeds its concurrency bound, and that re-running the surrounding
job (the queue's at-least-once retry) never executes an already-committed cost
centre twice.
"""

from __future__ import annotations

import asyncio

import pytest
from app.integration.fanout import BoundedFanout
from app.jobs import InMemoryJobQueue, Job, JobStatus


def test_fanout_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        BoundedFanout(limit=0)


COST_CENTRES = [f"cc-{i}" for i in range(12)]


def _variance(cc: str) -> dict[str, object]:
    # Deterministic stand-in for a per-cost-centre variance computation.
    n = int(cc.split("-")[1])
    return {"cost_centre": cc, "variance": float(n * 10)}


async def test_fanout_respects_the_concurrency_bound() -> None:
    limit = 4
    fanout = BoundedFanout(limit=limit)
    # A barrier of `limit` parties forces exactly `limit` tasks to overlap per wave,
    # so we prove the fan-out is concurrent AND never exceeds the bound.
    barrier = asyncio.Barrier(limit)

    items = [(cc, cc) for cc in COST_CENTRES]
    results = await fanout.run(items, lambda cc: _async(_variance(cc)), before=barrier.wait)

    assert fanout.peak_concurrency == limit  # reached the bound...
    assert fanout.peak_concurrency <= limit  # ...and never exceeded it
    assert len(results) == len(COST_CENTRES)
    assert {r["cost_centre"] for r in results} == set(COST_CENTRES)


async def test_no_double_execution_when_the_job_is_retried() -> None:
    execution_calls: dict[str, int] = {}
    done: set[str] = set()
    committed: list[str] = []
    poison = "cc-5"

    queue = InMemoryJobQueue()

    async def handler(job: Job, emit: object) -> dict[str, object]:
        fanout = BoundedFanout(limit=4, done=done, committed=committed)

        async def effect(cc: str) -> dict[str, float]:
            execution_calls[cc] = execution_calls.get(cc, 0) + 1
            # Transient failure on the first attempt only, after some work has
            # already committed in earlier concurrency waves.
            if cc == poison and job.attempts == 1:
                raise RuntimeError("transient downstream failure")
            return _variance(cc)

        await fanout.run([(cc, cc) for cc in COST_CENTRES], effect)
        return {"committed": list(fanout.committed)}

    queue.register("fpa.variance.load", handler)
    job = await queue.enqueue("fpa.variance.load", {}, max_attempts=3)
    await queue.drain()

    finished = queue.get(job.id)
    assert finished.status is JobStatus.COMPLETED
    assert finished.attempts == 2  # failed once, succeeded on retry

    # Every cost centre committed exactly once — no duplicates despite the retry.
    assert sorted(committed) == sorted(COST_CENTRES)
    assert len(committed) == len(set(committed))

    # Items that committed on attempt 1 were SKIPPED on retry (ran once); only the
    # poison item legitimately ran twice (failed, then succeeded).
    assert execution_calls[poison] == 2
    others_run_once = [cc for cc, n in execution_calls.items() if cc != poison and n == 1]
    assert len(others_run_once) >= 1
    assert all(n <= 2 for n in execution_calls.values())


async def _async(value: dict[str, object]) -> dict[str, object]:
    await asyncio.sleep(0)
    return value
