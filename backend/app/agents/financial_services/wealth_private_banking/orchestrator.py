"""Wealth & Private Banking orchestrators.

:class:`WealthOnboardingOrchestrator` builds the **hybrid** onboarding graph from
``claude2.md`` §5: ``client-onboarding-kyc`` (entry gate) → ``financial-planning``
‖ ``investment-advice`` (PARALLEL) → ``plan-reconciliation`` (fan-in).

:class:`RebalanceOrchestrator` and :class:`CreditOrchestrator` are the two
consequential action paths — each a short **sequential** chain whose gate
(``suitability-gate`` / ``credit-gate``) runs strictly before the gated action
(``discretionary-pm`` / ``private-banking``).
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
    sequential,
)
from app.agents.financial_services.wealth_private_banking.schemas import (
    CreditRequest,
    OnboardRequest,
    RebalanceRequest,
)
from app.agents.financial_services.wealth_private_banking.subagents import (
    ClientOnboardingKycSubagent,
    CreditGateSubagent,
    DiscretionaryPmSubagent,
    FinancialPlanningSubagent,
    InvestmentAdviceSubagent,
    PlanReconciliationSubagent,
    PrivateBankingSubagent,
    SuitabilityGateSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class WealthOnboardingOrchestrator(BaseOrchestrator[OnboardRequest]):
    """Hybrid onboarding + planning orchestrator."""

    group = "wealth-private-banking"
    mode = OrchestrationMode.HYBRID

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._correlation_id = correlation_id

    def build_graph(self, request: OnboardRequest) -> StepGraph:
        cid = request.client_id
        kyc = ClientOnboardingKycSubagent(cid, self._gateway, self._connectors).as_step()
        planning = FinancialPlanningSubagent(cid, self._gateway, self._connectors).as_step(
            depends_on=("client-onboarding-kyc",)
        )
        advice = InvestmentAdviceSubagent(cid, self._gateway).as_step(
            depends_on=("client-onboarding-kyc",)
        )
        reconcile = PlanReconciliationSubagent().as_step(
            depends_on=("financial-planning", "investment-advice")
        )
        return hybrid([kyc, planning, advice, reconcile])


class RebalanceOrchestrator(BaseOrchestrator[RebalanceRequest]):
    """Sequential, suitability-gated discretionary rebalance path."""

    group = "wealth-private-banking"
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

    def build_graph(self, request: RebalanceRequest) -> StepGraph:
        gate = SuitabilityGateSubagent(
            request.client_id, request.proposed_risk, self._connectors
        ).as_step()
        action = DiscretionaryPmSubagent(
            request.client_id, self._guardrails, correlation_id=self._correlation_id
        ).as_step()
        return sequential([gate, action])


class CreditOrchestrator(BaseOrchestrator[CreditRequest]):
    """Sequential, credit-gated Lombard facility path."""

    group = "wealth-private-banking"
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

    def build_graph(self, request: CreditRequest) -> StepGraph:
        gate = CreditGateSubagent(
            request.client_id, request.loan_amount, self._connectors
        ).as_step()
        action = PrivateBankingSubagent(
            request.client_id,
            request.loan_amount,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step()
        return sequential([gate, action])
