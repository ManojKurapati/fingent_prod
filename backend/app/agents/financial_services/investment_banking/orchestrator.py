"""Investment Banking orchestrator.

Builds the **hybrid** mandate graph documented in ``claude2.md`` §1: a sequential
spine ``coverage-origination -> modeling-diligence``, a parallel fan-out
(``materials-drafting`` ‖ ``compliance-gate``), and a gated execution tail — the
single execution subagent selected by deal type runs only behind the cleared
compliance gate.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.financial_services.investment_banking.schemas import DealType, MandateRequest
from app.agents.financial_services.investment_banking.subagents import (
    ComplianceGateSubagent,
    CoverageOriginationSubagent,
    EcmDcmLevfinSubagent,
    MaExecutionSubagent,
    MaterialsDraftingSubagent,
    ModelingDiligenceSubagent,
    RestructuringSubagent,
    _ExecutionSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


def _execution_for(
    deal_type: DealType, deal_id: str, guardrails: GuardrailEngine, correlation_id: str | None
) -> _ExecutionSubagent:
    """Select the single mutually-exclusive execution subagent for the deal type."""
    if deal_type == "ma":
        return MaExecutionSubagent(deal_id, guardrails, correlation_id=correlation_id)
    if deal_type == "restructuring":
        return RestructuringSubagent(deal_id, guardrails, correlation_id=correlation_id)
    return EcmDcmLevfinSubagent(deal_id, guardrails, correlation_id=correlation_id)


class InvestmentBankingOrchestrator(BaseOrchestrator[MandateRequest]):
    """Hybrid orchestrator for an investment-banking mandate."""

    group = "investment-banking"
    mode = OrchestrationMode.HYBRID

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        guardrails: GuardrailEngine,
        connectors: ToolRegistry,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._guardrails = guardrails
        self._connectors = connectors
        self._correlation_id = correlation_id

    def build_graph(self, request: MandateRequest) -> StepGraph:
        coverage = CoverageOriginationSubagent(
            request.deal_id, request.client, request.sector, self._gateway, self._connectors
        ).as_step()
        diligence = ModelingDiligenceSubagent(
            request.deal_id, self._gateway, self._connectors
        ).as_step(depends_on=("coverage-origination",))
        materials = MaterialsDraftingSubagent(self._gateway).as_step(
            depends_on=("modeling-diligence",)
        )
        compliance = ComplianceGateSubagent(
            request.client, self._gateway, self._connectors
        ).as_step(depends_on=("modeling-diligence",))
        execution = _execution_for(
            request.deal_type, request.deal_id, self._guardrails, self._correlation_id
        ).as_step(depends_on=("compliance-gate",))
        return hybrid([coverage, diligence, materials, compliance, execution])
