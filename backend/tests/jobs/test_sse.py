"""Tests for SSE progress streaming over the ProgressBus."""

import asyncio

from app.jobs import ProgressBus, ProgressEvent, format_sse


async def test_subscriber_receives_published_events_then_completion() -> None:
    bus = ProgressBus()
    received: list[ProgressEvent] = []

    async def consume() -> None:
        async for ev in bus.subscribe("job-1"):
            received.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber attach

    await bus.publish(ProgressEvent(job_id="job-1", type="status", payload={"state": "running"}))
    await bus.publish(ProgressEvent(job_id="job-1", type="status", payload={"state": "completed"}))
    await bus.close("job-1")

    await asyncio.wait_for(task, timeout=1.0)
    assert [e.payload["state"] for e in received] == ["running", "completed"]


async def test_events_are_isolated_per_job() -> None:
    bus = ProgressBus()
    await bus.publish(ProgressEvent(job_id="a", type="x", payload={"v": 1}))
    await bus.publish(ProgressEvent(job_id="b", type="x", payload={"v": 2}))
    assert [e.payload["v"] for e in bus.history("a")] == [1]
    assert [e.payload["v"] for e in bus.history("b")] == [2]


def test_format_sse_serialises_event_for_eventstream() -> None:
    ev = ProgressEvent(job_id="job-1", type="progress", payload={"done": 3, "total": 7})
    sse = format_sse(ev)
    assert sse["event"] == "progress"
    # data is JSON containing the payload and job id
    assert '"done": 3' in sse["data"]
    assert '"job_id": "job-1"' in sse["data"]
