"""Tests for the Subagent abstraction and BaseOrchestrator."""

from dataclasses import dataclass

from app.agents.core import (
    BaseOrchestrator,
    OrchestrationMode,
    Step,
    StepContext,
    StepEvent,
    Subagent,
    sequential,
)


@dataclass
class Echo(Subagent[str, str]):
    name: str
    suffix: str = "!"

    async def execute(self, ctx: StepContext) -> str:
        return f"{ctx.step}{self.suffix}"


async def test_subagent_as_step_runs_via_runner() -> None:
    sa = Echo(name="greet")
    step = sa.as_step()
    assert isinstance(step, Step)
    assert step.name == "greet"

    ctx = StepContext(step="greet", results={}, emit=_null_emit)
    assert await step.run(ctx) == "greet!"


async def test_subagent_as_step_carries_dependencies() -> None:
    step = Echo(name="b").as_step(depends_on=("a",))
    assert step.depends_on == ("a",)


class _DemoOrchestrator(BaseOrchestrator[list[str]]):
    group = "demo"
    mode = OrchestrationMode.SEQUENTIAL

    def build_graph(self, request: list[str]):  # type: ignore[no-untyped-def]
        return sequential([Echo(name=n).as_step() for n in request])


async def test_orchestrator_runs_built_graph() -> None:
    orch = _DemoOrchestrator()
    result = await orch.run(["a", "b"])
    assert result.order == ["a", "b"]
    assert result.outputs == {"a": "a!", "b": "b!"}


async def test_orchestrator_forwards_events_to_emit() -> None:
    seen: list[StepEvent] = []

    async def sink(ev: StepEvent) -> None:
        seen.append(ev)

    await _DemoOrchestrator().run(["only"], emit=sink)
    assert any(e.step == "only" for e in seen)


async def _null_emit(ev: StepEvent) -> None:
    return None
