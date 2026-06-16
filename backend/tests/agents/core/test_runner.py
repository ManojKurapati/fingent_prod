"""Tests for the deterministic orchestration runner (SEQUENTIAL/PARALLEL/HYBRID)."""

import asyncio

import pytest
from app.agents.core import (
    OrchestrationMode,
    Step,
    StepContext,
    StepEvent,
    StepFailedError,
    StepStatus,
    hybrid,
    parallel,
    run_graph,
    sequential,
)


def _record_step(name: str, log: list[str], *, depends_on: tuple[str, ...] = ()) -> Step:
    async def _run(ctx: StepContext) -> str:
        log.append(name)
        return f"out:{name}"

    return Step(name=name, run=_run, depends_on=depends_on)


async def test_sequential_runs_in_declared_order() -> None:
    log: list[str] = []
    graph = sequential([_record_step(n, log) for n in ("a", "b", "c")])
    assert graph.mode is OrchestrationMode.SEQUENTIAL

    result = await run_graph(graph)

    assert log == ["a", "b", "c"]
    assert result.order == ["a", "b", "c"]
    assert result.outputs == {"a": "out:a", "b": "out:b", "c": "out:c"}


async def test_parallel_steps_actually_run_concurrently() -> None:
    """Three parallel steps must overlap: a barrier only releases once all arrive."""
    started = asyncio.Barrier(3)

    async def _run(ctx: StepContext) -> str:
        # If steps ran sequentially this barrier would deadlock and time out.
        await started.wait()
        return ctx.step

    graph = parallel([Step(name=n, run=_run) for n in ("x", "y", "z")])
    assert graph.mode is OrchestrationMode.PARALLEL

    result = await asyncio.wait_for(run_graph(graph), timeout=1.0)

    assert set(result.outputs) == {"x", "y", "z"}


async def test_hybrid_respects_dependencies_and_passes_outputs() -> None:
    log: list[str] = []

    async def _join(ctx: StepContext) -> str:
        log.append("join")
        # join must see both parents' outputs
        return f"{ctx.results['left']}+{ctx.results['right']}"

    steps = [
        _record_step("root", log),
        _record_step("left", log, depends_on=("root",)),
        _record_step("right", log, depends_on=("root",)),
        Step(name="join", run=_join, depends_on=("left", "right")),
    ]
    graph = hybrid(steps)
    assert graph.mode is OrchestrationMode.HYBRID

    result = await run_graph(graph)

    assert log[0] == "root"
    assert log[-1] == "join"
    assert log.index("root") < log.index("left")
    assert log.index("root") < log.index("right")
    assert result.outputs["join"] == "out:left+out:right"


async def test_emits_lifecycle_events_in_order() -> None:
    log: list[str] = []
    events: list[StepEvent] = []

    async def _sink(ev: StepEvent) -> None:
        events.append(ev)

    graph = sequential([_record_step("a", log)])
    result = await run_graph(graph, emit=_sink)

    statuses = [(e.step, e.status) for e in events]
    assert statuses == [
        ("a", StepStatus.QUEUED),
        ("a", StepStatus.RUNNING),
        ("a", StepStatus.COMPLETED),
    ]
    # events are also captured on the result for replay/audit
    assert [(e.step, e.status) for e in result.events] == statuses


async def test_step_failure_raises_and_marks_failed() -> None:
    events: list[StepEvent] = []

    async def _boom(ctx: StepContext) -> str:
        raise ValueError("kaboom")

    async def _sink(ev: StepEvent) -> None:
        events.append(ev)

    graph = sequential([Step(name="bad", run=_boom)])

    with pytest.raises(StepFailedError) as exc:
        await run_graph(graph, emit=_sink)

    assert exc.value.step == "bad"
    assert isinstance(exc.value.__cause__, ValueError)
    assert any(e.status is StepStatus.FAILED and e.step == "bad" for e in events)


async def test_downstream_step_is_skipped_when_dependency_fails() -> None:
    ran: list[str] = []

    async def _boom(ctx: StepContext) -> str:
        raise RuntimeError("fail")

    async def _after(ctx: StepContext) -> str:
        ran.append("after")
        return "after"

    graph = hybrid(
        [
            Step(name="first", run=_boom),
            Step(name="after", run=_after, depends_on=("first",)),
        ]
    )

    with pytest.raises(StepFailedError):
        await run_graph(graph)

    assert ran == []  # downstream never executed
