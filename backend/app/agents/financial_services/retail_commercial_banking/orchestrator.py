"""Retail & Commercial Banking orchestrator.

:class:`RetailBankingOrchestrator` builds the **sequential** lending pipeline from
``claude2.md`` §6: an intake channel selected by ``channel`` heads a strict linear
chain ``intake → loan-origination → credit-analysis → underwriting → loan-funding``.
Each stage gates the next; funding is the consequential lend held behind the
underwriting credit-policy decision and the guardrail engine.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    sequential,
)
from app.agents.financial_services.retail_commercial_banking.schemas import (
    ApplicationRequest,
    Channel,
)
from app.agents.financial_services.retail_commercial_banking.subagents import (
    BranchOpsSubagent,
    CommercialRmSubagent,
    CreditAnalysisSubagent,
    LoanFundingSubagent,
    LoanOriginationSubagent,
    PersonalBankingSubagent,
    UnderwritingSubagent,
    _IntakeSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine

_INTAKE: dict[Channel, type[_IntakeSubagent]] = {
    "personal": PersonalBankingSubagent,
    "commercial": CommercialRmSubagent,
    "branch": BranchOpsSubagent,
}


class RetailBankingOrchestrator(BaseOrchestrator[ApplicationRequest]):
    """Sequential lending-pipeline orchestrator."""

    group = "retail-commercial-banking"
    mode = OrchestrationMode.SEQUENTIAL

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

    def build_graph(self, request: ApplicationRequest) -> StepGraph:
        app_id = request.application_id
        intake = _INTAKE[request.channel](request.applicant, self._gateway).as_step()
        origination = LoanOriginationSubagent(app_id, self._gateway, self._connectors).as_step()
        analysis = CreditAnalysisSubagent(app_id, self._gateway, self._connectors).as_step()
        underwriting = UnderwritingSubagent(
            app_id, request.loan_amount, self._gateway, self._connectors
        ).as_step()
        funding = LoanFundingSubagent(
            app_id, self._guardrails, correlation_id=self._correlation_id
        ).as_step()
        return sequential([intake, origination, analysis, underwriting, funding])
