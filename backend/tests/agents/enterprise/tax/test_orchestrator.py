"""Orchestrator-graph tests for Tax.

Provision is **hybrid** (claude1.md §6): a parallel fan-out by tax type
(``direct-tax-compliance`` ‖ ``indirect-tax`` ‖ ``transfer-pricing`` ‖
``international-tax`` ‖ ``audit-defence``) that fans in to ``tax-provision``.
We assert the fan-in dependency shape, that the compliance streams run
*concurrently*, that the provision lands last, and that the standalone filing path
is sequential and gates the external submission.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.tax.orchestrator import TaxFilingOrchestrator, TaxProvisionOrchestrator
from app.agents.enterprise.tax.schemas import FileRequest, ProvisionRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

# Prompts emitted by the parallel compliance streams (must overlap).
_COMPLIANCE_PROMPTS = {
    "compute direct tax",
    "compute indirect tax",
    "document transfer pricing",
    "assess international tax",
    "monitor disputes",
}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    return build_fake_connector(
        store=FakeStore(
            data={
                "income:US": "1000",
                "rate:US": "0.21",
                "income:UK": "500",
                "rate:UK": "0.25",
                "vat_out:US": "300",
                "vat_in:US": "120",
                "intercompany:US": "40",
                "foreign_tax:UK": "30",
                "dispute:US": "1",
            }
        )
    )


def _provision_orch(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> TaxProvisionOrchestrator:
    return TaxProvisionOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        connectors=connectors or _seeded_connectors(),
    )


def _request() -> ProvisionRequest:
    return ProvisionRequest(period="FY26", jurisdictions=["US", "UK"])


def test_provision_graph_is_hybrid_fanout_to_provision() -> None:
    graph = _provision_orch().build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    # the four compliance streams + the standing audit-defence stream are roots
    for root in (
        "direct-tax-compliance",
        "indirect-tax",
        "transfer-pricing",
        "international-tax",
        "audit-defence",
    ):
        assert by_name[root].depends_on == ()
    # provision fans in on the four compliance streams (not the standing stream)
    assert set(by_name["tax-provision"].depends_on) == {
        "direct-tax-compliance",
        "indirect-tax",
        "transfer-pricing",
        "international-tax",
    }


async def test_compliance_streams_run_concurrently() -> None:
    """The five standing/compliance streams must overlap (barrier deadlocks else)."""
    barrier = asyncio.Barrier(len(_COMPLIANCE_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _COMPLIANCE_PROMPTS:
            await barrier.wait()
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch = _provision_orch(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert "tax-provision" in result.outputs


async def test_provision_fans_in_last() -> None:
    result = await _provision_orch().run(_request())
    assert result.order[-1] == "tax-provision"
    prov = result.outputs["tax-provision"]
    assert prov["current"] == pytest.approx(335.0)
    # deferred = TP(40) + intl(30) = 70 -> total_tax 405 over income 1500
    assert prov["deferred"] == pytest.approx(70.0)
    assert prov["etr"] == pytest.approx(405.0 / 1500.0)


# --- standalone filing path (sequential, gated) ---------------------------


def test_filing_graph_is_sequential() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = TaxFilingOrchestrator(gateway=ClaudeGateway(transport=_stub), guardrails=guardrails)
    graph = orch.build_graph(FileRequest(return_id="ret-US-2026", jurisdiction="US"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == ["file-return"]


async def test_filing_run_holds_submission_for_approval() -> None:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = TaxFilingOrchestrator(gateway=ClaudeGateway(transport=_stub), guardrails=guardrails)
    result = await orch.run(FileRequest(return_id="ret-US-2026", jurisdiction="US"))
    assert result.outputs["file-return"]["filed"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "tax_file_return"
