"""Orchestrator-graph tests for Accounting & Controllership.

Asserts the hybrid shape documented in ``claude1.md`` §3: a sequential close
spine gated by ``close-orchestration``, a PARALLEL sub-ledger fan-out
(``journal-entries`` ‖ ``fixed-assets`` ‖ ``cost-inventory`` ‖
``technical-accounting``), a fan-in to ``reconciliations``, then
``consolidations`` sequenced strictly last. Concurrency of the sub-ledgers is
proven with an ``asyncio.Barrier`` (deadlocks unless they overlap).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.accounting.orchestrator import AccountingCloseOrchestrator
from app.agents.enterprise.accounting.schemas import CloseRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_SUBLEDGER_STEPS = {
    "prepare journal entries",
    "compute depreciation",
    "value inventory",
    "asc606 review",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "accrual:e1": "300",
            "accrual:e2": "200",
            "asset_cost:e1": "6000",
            "inventory:e1": "1100",
            "std_cost:e1": "1000",
            "contract:e1": "1200",
            "gl_control": "999999",
            "entity_balance:e1": "1000",
            "fx_rate:e1": "1.0",
            "ic:e1": "0",
            "entity_balance:e2": "500",
            "fx_rate:e2": "1.0",
            "ic:e2": "0",
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[AccountingCloseOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = AccountingCloseOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _request() -> CloseRequest:
    return CloseRequest(period="FY26-M06", entities=["e1", "e2"])


def test_graph_is_hybrid_with_spine_fanout_and_sequenced_consolidation() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # close-orchestration is the head that gates the period
    assert by_name["close-orchestration"].depends_on == ()
    # sub-ledgers fan out in parallel off the open period, mutually independent
    for sub in ("journal-entries", "fixed-assets", "cost-inventory", "technical-accounting"):
        assert by_name[sub].depends_on == ("close-orchestration",)
    # reconciliations fans in from every sub-ledger
    assert set(by_name["reconciliations"].depends_on) == {
        "journal-entries",
        "fixed-assets",
        "cost-inventory",
        "technical-accounting",
    }
    # consolidations is sequenced strictly after reconciliations (all books closed)
    assert by_name["consolidations"].depends_on == ("reconciliations",)


async def test_subledgers_run_concurrently() -> None:
    """journal-entries ‖ fixed-assets ‖ cost-inventory ‖ technical-accounting overlap."""
    barrier = asyncio.Barrier(len(_SUBLEDGER_STEPS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _SUBLEDGER_STEPS:
            await barrier.wait()  # only releases if all four overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert "consolidations" in result.outputs


async def test_close_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    # period opens before any sub-ledger
    assert pos["close-orchestration"] < pos["journal-entries"]
    assert pos["close-orchestration"] < pos["fixed-assets"]
    # reconciliations after every sub-ledger; consolidations strictly last
    assert pos["journal-entries"] < pos["reconciliations"]
    assert pos["fixed-assets"] < pos["reconciliations"]
    assert pos["reconciliations"] < pos["consolidations"]
    assert result.order[-1] == "consolidations"


async def test_run_holds_ledger_post_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())
    # the GL post is held, never executed without approval (default-deny)
    assert result.outputs["journal-entries"]["posted"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "accounting_post_journal_entry"
    assert pending[0].approver_role == "controller"
