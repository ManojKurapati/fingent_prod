"""Orchestrator-graph tests for Transactional / Operational Finance.

The headline operational cycle is **parallel with one local sequence** (claude1.md
§4): AP ‖ payroll ‖ procurement ‖ (billing -> accounts-receivable -> collections).
Structurally a HYBRID DAG — we assert (a) the four lane roots run *concurrently*,
(b) the O2C chain ordering holds, and (c) cash-movement actions are held for
approval. The standalone AP payment run is a pure PARALLEL fan-out per vendor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.transactional.orchestrator import (
    ApPaymentRunOrchestrator,
    TransactionalOrchestrator,
)
from app.agents.enterprise.transactional.schemas import CycleRequest, PaymentRunRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

# Prompts emitted by the four independent lane roots (must overlap).
_LANE_ROOT_PROMPTS = {
    "match AP invoices",
    "run payroll",
    "track procurement spend",
    "generate invoices",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(
            data={
                "invoice:v1": "500",
                "po:v1": "500",
                "invoice:v2": "200",
                "po:v2": "200",
                "payroll:e1": "1000",
                "spend:total": "80",
                "budget:total": "100",
                "contract:c1": "300",
                "contract:c2": "150",
                "cash:c1": "300",
                "cash:c2": "100",
            }
        )
    )


def _cycle_orch(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[TransactionalOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = TransactionalOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _cycle_request() -> CycleRequest:
    return CycleRequest(
        period="2026-06", vendors=["v1", "v2"], customers=["c1", "c2"], employees=["e1"]
    )


def test_cycle_graph_is_hybrid_with_parallel_lanes_and_o2c_sequence() -> None:
    orch, _ = _cycle_orch()
    graph = orch.build_graph(_cycle_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # four independent lane roots
    assert by_name["accounts-payable"].depends_on == ()
    assert by_name["payroll"].depends_on == ()
    assert by_name["procurement"].depends_on == ()
    assert by_name["billing"].depends_on == ()
    # the single local O2C sequence
    assert by_name["accounts-receivable"].depends_on == ("billing",)
    assert by_name["collections"].depends_on == ("accounts-receivable",)


async def test_lane_roots_run_concurrently() -> None:
    """AP ‖ payroll ‖ procurement ‖ billing must overlap (barrier deadlocks else)."""
    barrier = asyncio.Barrier(len(_LANE_ROOT_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _LANE_ROOT_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _cycle_orch(transport=gated)
    result = await asyncio.wait_for(orch.run(_cycle_request()), timeout=1.0)
    assert result.outputs["collections"]["overdue"] == ["c2"]


async def test_o2c_ordering_holds() -> None:
    orch, _ = _cycle_orch()
    result = await orch.run(_cycle_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["billing"] < pos["accounts-receivable"]
    assert pos["accounts-receivable"] < pos["collections"]


async def test_cycle_holds_cash_movements_for_approval() -> None:
    orch, guardrails = _cycle_orch()
    await orch.run(_cycle_request())
    # AP payment run + payroll disbursement are both held (default-deny)
    held = guardrails.pending()
    assert len(held) == 2
    assert all(r.tool_name == "transactional_execute_payment" for r in held)


# --- standalone AP payment run (pure parallel) ----------------------------


def test_payment_run_graph_is_parallel() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = ApPaymentRunOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    graph = orch.build_graph(PaymentRunRequest(period="2026-06", vendors=["v1", "v2"]))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert {s.name for s in graph.steps} == {"match:v1", "match:v2"}
    assert all(s.depends_on == () for s in graph.steps)


async def test_payment_run_matches_concurrently_and_holds_payments() -> None:
    barrier = asyncio.Barrier(2)

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt == "3-way match":
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = ApPaymentRunOrchestrator(
        gateway=ClaudeGateway(transport=gated),
        guardrails=guardrails,
        connectors=_seeded_connectors(),
    )
    result = await asyncio.wait_for(
        orch.run(PaymentRunRequest(period="2026-06", vendors=["v1", "v2"])), timeout=1.0
    )
    assert result.outputs["match:v1"]["matched"] is True
    # both vendors match (equal invoice/po) -> two payments held
    assert len(guardrails.pending()) == 2
