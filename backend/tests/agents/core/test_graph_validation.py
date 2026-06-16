"""Tests for StepGraph construction & validation invariants."""

import pytest
from app.agents.core import (
    GraphValidationError,
    OrchestrationMode,
    Step,
    StepGraph,
    hybrid,
    parallel,
    sequential,
)


async def _noop(ctx: object) -> None:
    return None


def _s(name: str, deps: tuple[str, ...] = ()) -> Step:
    return Step(name=name, run=_noop, depends_on=deps)


def test_sequential_builder_wires_a_linear_chain() -> None:
    graph = sequential([_s("a"), _s("b"), _s("c")])
    by_name = {s.name: s for s in graph.steps}
    assert by_name["a"].depends_on == ()
    assert by_name["b"].depends_on == ("a",)
    assert by_name["c"].depends_on == ("b",)


def test_parallel_builder_has_no_dependencies() -> None:
    graph = parallel([_s("a"), _s("b")])
    assert all(s.depends_on == () for s in graph.steps)


def test_duplicate_step_names_rejected() -> None:
    with pytest.raises(GraphValidationError):
        hybrid([_s("a"), _s("a")])


def test_missing_dependency_rejected() -> None:
    with pytest.raises(GraphValidationError):
        hybrid([_s("a", deps=("ghost",))])


def test_cycle_rejected() -> None:
    with pytest.raises(GraphValidationError):
        hybrid([_s("a", deps=("b",)), _s("b", deps=("a",))])


def test_parallel_mode_rejects_dependencies() -> None:
    with pytest.raises(GraphValidationError):
        StepGraph(mode=OrchestrationMode.PARALLEL, steps=(_s("a"), _s("b", deps=("a",))))


def test_sequential_mode_rejects_branching() -> None:
    # two steps depending on the same parent is not a linear chain
    with pytest.raises(GraphValidationError):
        StepGraph(
            mode=OrchestrationMode.SEQUENTIAL,
            steps=(_s("a"), _s("b", deps=("a",)), _s("c", deps=("a",))),
        )


def test_empty_graph_rejected() -> None:
    with pytest.raises(GraphValidationError):
        hybrid([])


def test_self_dependency_rejected() -> None:
    with pytest.raises(GraphValidationError):
        hybrid([_s("a", deps=("a",))])


def test_sequential_mode_rejects_multiple_dependencies() -> None:
    with pytest.raises(GraphValidationError):
        StepGraph(
            mode=OrchestrationMode.SEQUENTIAL,
            steps=(_s("a"), _s("b"), _s("c", deps=("a", "b"))),
        )


def test_sequential_mode_requires_single_source() -> None:
    # two independent sources -> not a single chain
    with pytest.raises(GraphValidationError):
        StepGraph(
            mode=OrchestrationMode.SEQUENTIAL,
            steps=(_s("a"), _s("b")),
        )


def test_order_returns_topological_order() -> None:
    graph = hybrid([_s("a"), _s("b", deps=("a",))])
    assert graph.order() == ["a", "b"]
