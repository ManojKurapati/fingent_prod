"""Orchestrator-graph tests for Investment Banking.

Asserts the documented HYBRID shape (origination -> diligence -> {materials ‖
compliance-gate -> execution}), that the materials/compliance branches overlap,
that the execution subagent is selected by deal type, and that the mandatory
compliance gate blocks the client-facing launch on a deny.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.investment_banking.orchestrator import (
    InvestmentBankingOrchestrator,
)
from app.agents.financial_services.investment_banking.schemas import MandateRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_OVERLAP_PROMPTS = {"draft materials", "review conflicts"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(*, conflict: str = "clear") -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(data={"financials:d1": "500", "conflict:acme": conflict})
    )


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[InvestmentBankingOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = InvestmentBankingOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def _request(deal_type: str = "ma") -> MandateRequest:
    return MandateRequest(deal_id="d1", client="acme", deal_type=deal_type, sector="tech")


def test_graph_is_hybrid_with_diligence_spine_and_gated_execution() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request("ma"))
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["coverage-origination"].depends_on == ()
    assert by_name["modeling-diligence"].depends_on == ("coverage-origination",)
    # materials and the compliance gate both fan out from diligence (parallel)
    assert by_name["materials-drafting"].depends_on == ("modeling-diligence",)
    assert by_name["compliance-gate"].depends_on == ("modeling-diligence",)
    # execution is gated: it cannot run until the compliance gate clears
    assert by_name["ma-execution"].depends_on == ("compliance-gate",)


def test_execution_subagent_is_selected_by_deal_type() -> None:
    orch, _ = _orchestrator()
    for deal_type, step in (
        ("ma", "ma-execution"),
        ("ecm", "ecm-dcm-levfin"),
        ("dcm", "ecm-dcm-levfin"),
        ("levfin", "ecm-dcm-levfin"),
        ("restructuring", "restructuring"),
    ):
        names = {s.name for s in orch.build_graph(_request(deal_type)).steps}
        assert step in names
        # mutually exclusive: only the selected execution subagent appears
        others = {"ma-execution", "ecm-dcm-levfin", "restructuring"} - {step}
        assert names.isdisjoint(others)


async def test_materials_and_compliance_run_concurrently() -> None:
    """materials-drafting ‖ compliance-gate must overlap (barrier deadlocks else)."""
    barrier = asyncio.Barrier(len(_OVERLAP_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _OVERLAP_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request("ma")), timeout=1.0)
    assert result.outputs["compliance-gate"]["decision"] == "PASS"


async def test_clean_run_holds_launch_for_human_approval() -> None:
    orch, guardrails = _orchestrator(connectors=_connectors(conflict="clear"))
    result = await orch.run(_request("ma"))
    assert result.outputs["compliance-gate"]["decision"] == "PASS"
    assert result.outputs["ma-execution"]["blocked"] is False
    assert result.outputs["ma-execution"]["launched"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "ib_launch_mandate"


async def test_conflicted_run_blocks_launch_before_the_gate() -> None:
    orch, guardrails = _orchestrator(connectors=_connectors(conflict="flagged"))
    result = await orch.run(_request("ma"))
    assert result.outputs["compliance-gate"]["decision"] == "DENY"
    assert result.outputs["ma-execution"]["blocked"] is True
    # the consequential launch never reaches the approval queue
    assert guardrails.pending() == []


async def test_execution_ordering_follows_the_gate() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request("ma"))
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["coverage-origination"] < pos["modeling-diligence"]
    assert pos["modeling-diligence"] < pos["compliance-gate"]
    assert pos["compliance-gate"] < pos["ma-execution"]
