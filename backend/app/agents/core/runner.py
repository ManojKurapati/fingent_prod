"""Deterministic orchestration runner.

The runner is mode-agnostic: it executes the validated dependency DAG, launching
every ready step concurrently and respecting dependencies. SEQUENTIAL graphs are
linear chains (so steps run in order); PARALLEL graphs have no edges (so all run
at once); HYBRID graphs are arbitrary DAGs (independent branches overlap).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.agents.core.models import (
    EmitFn,
    RunResult,
    Step,
    StepContext,
    StepEvent,
    StepFailedError,
    StepGraph,
    StepStatus,
)


async def run_graph(graph: StepGraph, *, emit: EmitFn | None = None) -> RunResult:
    """Execute ``graph``, returning outputs, completion order, and the event log.

    Independent steps run concurrently. The first step to raise fails the whole
    run fast: pending steps are cancelled and a :class:`StepFailedError` is raised.
    """
    events: list[StepEvent] = []
    outputs: dict[str, Any] = {}
    order: list[str] = []

    async def _emit(event: StepEvent) -> None:
        events.append(event)
        if emit is not None:
            await emit(event)

    steps_by_name = {s.name: s for s in graph.steps}
    indegree = {s.name: len(s.depends_on) for s in graph.steps}
    dependents: dict[str, list[str]] = defaultdict(list)
    for s in graph.steps:
        for dep in s.depends_on:
            dependents[dep].append(s.name)

    for name in graph.order():
        await _emit(StepEvent(step=name, status=StepStatus.QUEUED))

    async def _run_one(step: Step) -> Any:
        await _emit(StepEvent(step=step.name, status=StepStatus.RUNNING))
        ctx = StepContext(
            step=step.name,
            results={dep: outputs[dep] for dep in step.depends_on},
            emit=_emit,
        )
        return await step.run(ctx)

    running: dict[asyncio.Task[Any], str] = {}

    def _launch(name: str) -> None:
        task = asyncio.create_task(_run_one(steps_by_name[name]), name=name)
        running[task] = name

    for name, deg in indegree.items():
        if deg == 0:
            _launch(name)

    try:
        while running:
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                name = running.pop(task)
                exc = task.exception()
                if exc is not None:
                    await _emit(StepEvent(step=name, status=StepStatus.FAILED, detail=str(exc)))
                    raise StepFailedError(name, exc)
                outputs[name] = task.result()
                order.append(name)
                await _emit(StepEvent(step=name, status=StepStatus.COMPLETED))
                for child in dependents.get(name, ()):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        _launch(child)
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    return RunResult(outputs=outputs, order=order, events=events)
