"""Tracer unit tests: spans capture name, latency, and attributes."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.observability import Tracer, TraceSpan


def _fake_clock() -> Callable[[], float]:
    ticks = iter([1.0, 1.5, 10.0, 12.0])
    return lambda: next(ticks)


async def test_span_records_name_latency_and_attributes() -> None:
    tracer = Tracer(clock=_fake_clock())

    async with tracer.span("agent.run:fpa", group="fpa") as span:
        span.set("calls", 3)

    assert len(tracer.spans) == 1
    recorded = tracer.spans[0]
    assert isinstance(recorded, TraceSpan)
    assert recorded.name == "agent.run:fpa"
    assert recorded.attributes["group"] == "fpa"
    assert recorded.attributes["calls"] == 3
    assert recorded.duration == pytest.approx(0.5)


async def test_span_is_recorded_even_when_body_raises() -> None:
    tracer = Tracer(clock=_fake_clock())

    with pytest.raises(ValueError):
        async with tracer.span("agent.run:boom"):
            raise ValueError("kaboom")

    assert len(tracer.spans) == 1
    assert tracer.spans[0].name == "agent.run:boom"
    assert tracer.spans[0].duration == pytest.approx(0.5)


async def test_multiple_spans_accumulate_in_order() -> None:
    tracer = Tracer(clock=_fake_clock())
    async with tracer.span("first"):
        pass
    async with tracer.span("second"):
        pass
    assert [s.name for s in tracer.spans] == ["first", "second"]
