"""Subagent abstraction and BaseOrchestrator — FROZEN CONTRACT.

A ``Subagent`` is a stateless, tool-using task worker: typed input in, typed
output out, plus lifecycle events. A ``BaseOrchestrator`` owns a group's plan: it
builds a :class:`StepGraph` from a request and runs it deterministically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.agents.core.models import (
    EmitFn,
    OrchestrationMode,
    RunResult,
    Step,
    StepContext,
    StepGraph,
)
from app.agents.core.runner import run_graph


class Subagent[I, O](ABC):
    """One responsibility cluster. Stateless worker addressable only by its parent.

    Subclasses set ``name`` and implement :meth:`execute`. Wrap into a graph node
    with :meth:`as_step`.
    """

    name: str

    @abstractmethod
    async def execute(self, ctx: StepContext) -> O:
        """Run the subagent's work, returning its typed output."""
        raise NotImplementedError

    def as_step(self, *, depends_on: tuple[str, ...] = ()) -> Step:
        """Adapt this subagent into a :class:`Step` for the orchestration runner."""

        async def _run(ctx: StepContext) -> object:
            return await self.execute(ctx)

        return Step(name=self.name, run=_run, depends_on=depends_on)


class BaseOrchestrator[R](ABC):
    """A group-level orchestrator: builds a plan and runs it.

    Subclasses set ``group`` (the route segment / audit actor) and ``mode`` (the
    documented orchestration shape) and implement :meth:`build_graph`.
    """

    group: str
    mode: OrchestrationMode

    @abstractmethod
    def build_graph(self, request: R) -> StepGraph:
        """Produce the step graph for ``request``. Must honour ``self.mode``."""
        raise NotImplementedError

    async def run(self, request: R, *, emit: EmitFn | None = None) -> RunResult:
        """Build and execute the plan for ``request``."""
        graph = self.build_graph(request)
        return await run_graph(graph, emit=emit)


__all__ = ["BaseOrchestrator", "StepContext", "Subagent"]
