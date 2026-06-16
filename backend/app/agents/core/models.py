"""Core orchestration data types — FROZEN CONTRACT.

These types are imported by every group-agent. Do not change their shape without
a coordinated migration: wave 2/3 sessions depend on them being stable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OrchestrationMode(StrEnum):
    """Shape of a step graph, chosen by data dependency (not taste)."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HYBRID = "hybrid"


class StepStatus(StrEnum):
    """Lifecycle status emitted for every step as it runs."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepEvent:
    """A single lifecycle event for a step, suitable for SSE and the audit log."""

    step: str
    status: StepStatus
    detail: str | None = None


# An async sink for step events (e.g. an SSE publisher or audit recorder).
EmitFn = Callable[[StepEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class StepContext:
    """What a step receives when it runs.

    ``results`` contains the outputs of this step's declared dependencies only
    (guaranteed complete). ``emit`` lets a step publish sub-progress events.
    """

    step: str
    results: Mapping[str, Any]
    emit: EmitFn


# A step body: an async callable taking its context and returning any output.
StepRun = Callable[[StepContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Step:
    """One node in an orchestration graph (typically wraps a subagent)."""

    name: str
    run: StepRun
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of running a step graph."""

    outputs: dict[str, Any]
    order: list[str]
    events: list[StepEvent] = field(default_factory=list)


class GraphValidationError(ValueError):
    """Raised when a StepGraph violates structural or mode invariants."""


class StepFailedError(RuntimeError):
    """Raised when a step's body raises; ``__cause__`` holds the original error."""

    def __init__(self, step: str, cause: BaseException) -> None:
        super().__init__(f"step {step!r} failed: {cause!r}")
        self.step = step
        self.__cause__ = cause


def _topological_order(steps: tuple[Step, ...]) -> list[str]:
    """Return a topological order, raising GraphValidationError on cycles."""
    names = {s.name for s in steps}
    deps = {s.name: set(s.depends_on) for s in steps}
    order: list[str] = []
    ready = sorted(n for n, d in deps.items() if not d)
    remaining = dict(deps)
    while ready:
        node = ready.pop(0)
        order.append(node)
        del remaining[node]
        newly: list[str] = []
        for other, d in remaining.items():
            if node in d:
                d.discard(node)
                if not d:
                    newly.append(other)
        ready.extend(sorted(newly))
        ready.sort()
    if remaining:
        raise GraphValidationError(f"cycle detected among steps: {sorted(remaining)}")
    assert len(order) == len(names)
    return order


@dataclass(frozen=True)
class StepGraph:
    """A validated graph of steps plus its declared orchestration mode."""

    mode: OrchestrationMode
    steps: tuple[Step, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise GraphValidationError("a step graph must contain at least one step")

        names = [s.name for s in self.steps]
        if len(names) != len(set(names)):
            raise GraphValidationError("step names must be unique")
        name_set = set(names)

        for s in self.steps:
            for dep in s.depends_on:
                if dep not in name_set:
                    raise GraphValidationError(f"step {s.name!r} depends on unknown step {dep!r}")
                if dep == s.name:
                    raise GraphValidationError(f"step {s.name!r} depends on itself")

        _topological_order(self.steps)  # cycle check
        self._validate_mode()

    def _validate_mode(self) -> None:
        if self.mode is OrchestrationMode.PARALLEL:
            if any(s.depends_on for s in self.steps):
                raise GraphValidationError("PARALLEL graphs must have no dependencies")
        elif self.mode is OrchestrationMode.SEQUENTIAL:
            self._validate_linear()

    def _validate_linear(self) -> None:
        # Each step depends on at most one other; each step is depended on by at
        # most one other; exactly one source and one sink.
        dependents: dict[str, int] = {s.name: 0 for s in self.steps}
        for s in self.steps:
            if len(s.depends_on) > 1:
                raise GraphValidationError(
                    f"SEQUENTIAL graph is not linear: {s.name!r} has multiple dependencies"
                )
            for dep in s.depends_on:
                dependents[dep] += 1
        if any(count > 1 for count in dependents.values()):
            raise GraphValidationError(
                "SEQUENTIAL graph is not linear: a step has multiple successors"
            )
        sources = [s.name for s in self.steps if not s.depends_on]
        if len(sources) != 1:
            raise GraphValidationError("SEQUENTIAL graph must have exactly one source step")

    def order(self) -> list[str]:
        """A valid topological order of step names."""
        return _topological_order(self.steps)


def _as_tuple(steps: Iterable[Step]) -> tuple[Step, ...]:
    return tuple(steps)


def sequential(steps: Iterable[Step]) -> StepGraph:
    """Build a SEQUENTIAL graph, auto-wiring each step to the previous one."""
    items = _as_tuple(steps)
    wired: list[Step] = []
    prev: str | None = None
    for s in items:
        wired.append(Step(name=s.name, run=s.run, depends_on=() if prev is None else (prev,)))
        prev = s.name
    return StepGraph(mode=OrchestrationMode.SEQUENTIAL, steps=tuple(wired))


def parallel(steps: Iterable[Step]) -> StepGraph:
    """Build a PARALLEL graph; any declared dependencies are stripped."""
    stripped = tuple(Step(name=s.name, run=s.run) for s in steps)
    return StepGraph(mode=OrchestrationMode.PARALLEL, steps=stripped)


def hybrid(steps: Iterable[Step]) -> StepGraph:
    """Build a HYBRID graph honoring each step's declared ``depends_on``."""
    return StepGraph(mode=OrchestrationMode.HYBRID, steps=_as_tuple(steps))
