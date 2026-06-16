"""Lightweight per-agent tracing.

A :class:`Tracer` collects :class:`TraceSpan` records. Each span captures a name,
start/end timestamps (so latency is derivable), and arbitrary attributes (e.g.
token counts and cost for an agent run). The clock is injectable so tests are
deterministic; production passes ``time.perf_counter``.

This is the in-process reference. A production tracer forwards the same spans to
OpenTelemetry / an APM backend — the contract (name, latency, attributes) is
identical.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class TraceSpan:
    """An immutable, completed trace span."""

    name: str
    start: float
    end: float
    attributes: Mapping[str, Any]

    @property
    def duration(self) -> float:
        """Wall-clock latency of the span, in the clock's units (seconds)."""
        return self.end - self.start


class _OpenSpan:
    """A span being recorded; attributes can be set until the context exits."""

    def __init__(self, name: str, start: float, attributes: Mapping[str, Any]) -> None:
        self.name = name
        self.start = start
        self.attributes: dict[str, Any] = dict(attributes)

    def set(self, key: str, value: Any) -> None:
        """Attach an attribute to the span (e.g. token usage, cost)."""
        self.attributes[key] = value


class Tracer:
    """Collects spans for the current process/run."""

    def __init__(self, *, clock: Clock = time.perf_counter) -> None:
        self._clock = clock
        self._spans: list[TraceSpan] = []

    @property
    def spans(self) -> tuple[TraceSpan, ...]:
        """An immutable snapshot of recorded spans, in completion order."""
        return tuple(self._spans)

    @asynccontextmanager
    async def span(self, name: str, **attributes: Any):  # type: ignore[no-untyped-def]
        """Record a span around an async block.

        The span is recorded even if the body raises (so failures are observable).
        """
        open_span = _OpenSpan(name, self._clock(), attributes)
        try:
            yield open_span
        finally:
            end = self._clock()
            self._spans.append(
                TraceSpan(
                    name=open_span.name,
                    start=open_span.start,
                    end=end,
                    attributes=dict(open_span.attributes),
                )
            )
