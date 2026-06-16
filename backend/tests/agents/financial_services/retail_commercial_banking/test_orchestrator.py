"""Orchestrator-graph tests for Retail & Commercial Banking.

Lending is a strict SEQUENTIAL pipeline: intake -> loan-origination ->
credit-analysis -> underwriting -> credit gate -> funding. Asserts the linear
shape, the channel selection, the run ordering, and that funding is blocked when
underwriting declines.
"""

from __future__ import annotations

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.retail_commercial_banking.orchestrator import (
    RetailBankingOrchestrator,
)
from app.agents.financial_services.retail_commercial_banking.schemas import ApplicationRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(**store: str) -> ToolRegistry:
    return build_fake_connector(store=FakeStore(data=dict(store)))


def _approve_store() -> dict[str, str]:
    return {"bank:income:a1": "100", "bank:debt_service:a1": "20", "bank:collateral:a1": "200"}


def _orchestrator(
    *, connectors: ToolRegistry | None = None
) -> tuple[RetailBankingOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = RetailBankingOrchestrator(
        gateway=ClaudeGateway(transport=_stub),
        guardrails=guardrails,
        connectors=connectors or _connectors(**_approve_store()),
    )
    return orch, guardrails


def _request(channel: str = "personal") -> ApplicationRequest:
    return ApplicationRequest(
        application_id="a1", channel=channel, applicant="ann", loan_amount=100.0
    )


def test_graph_is_a_sequential_lending_pipeline() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request("personal"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == [
        "personal-banking",
        "loan-origination",
        "credit-analysis",
        "underwriting",
        "loan-funding",
    ]


def test_intake_channel_is_selected_by_request() -> None:
    orch, _ = _orchestrator()
    for channel, head in (
        ("personal", "personal-banking"),
        ("commercial", "commercial-rm"),
        ("branch", "branch-ops"),
    ):
        steps = [s.name for s in orch.build_graph(_request(channel)).steps]
        assert steps[0] == head
        # exactly one intake channel heads the pipeline
        assert steps.count(head) == 1


async def test_pipeline_runs_in_strict_order() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request("personal"))
    assert result.order == [
        "personal-banking",
        "loan-origination",
        "credit-analysis",
        "underwriting",
        "loan-funding",
    ]


async def test_approved_application_holds_disbursement_for_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request("personal"))
    assert result.outputs["underwriting"]["decision"] == "approve"
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "banking_fund_loan"
    assert result.outputs["loan-funding"]["funded"] is False


async def test_declined_application_funds_nothing() -> None:
    # DSR 0.7 -> underwriting declines -> credit gate blocks funding
    connectors = _connectors(
        **{"bank:income:a1": "100", "bank:debt_service:a1": "70", "bank:collateral:a1": "500"}
    )
    orch, guardrails = _orchestrator(connectors=connectors)
    result = await orch.run(_request("personal"))
    assert result.outputs["underwriting"]["decision"] == "decline"
    assert result.outputs["loan-funding"]["blocked"] is True
    assert guardrails.pending() == []
