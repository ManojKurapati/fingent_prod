"""Product/Strategy/Client orchestrators.

:class:`ProductInitiativeOrchestrator` builds the **sequential** product-definition
chain (``claude2.md`` §12): ``product-management -> pricing -> compliance-filing
-> launch`` — the mandatory compliance/regulatory-filing gate precedes the
consequential launch.

:class:`ProductCommercialOrchestrator` builds the **parallel** post-launch
commercial loop: ``sales-distribution`` ‖ ``client-onboarding`` ‖
``client-services`` (onboarding is internally KYC-gated before activation).
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    parallel,
    sequential,
)
from app.agents.financial_services.product_strategy_client.schemas import (
    CommercialRequest,
    InitiativeRequest,
)
from app.agents.financial_services.product_strategy_client.subagents import (
    ClientOnboardingSubagent,
    ClientServicesSubagent,
    ComplianceFilingGateSubagent,
    LaunchSubagent,
    PricingSubagent,
    ProductManagementSubagent,
    SalesDistributionSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class ProductInitiativeOrchestrator(BaseOrchestrator[InitiativeRequest]):
    """Sequential discovery -> pricing -> filing-gate -> launch."""

    group = "product"
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

    def build_graph(self, request: InitiativeRequest) -> StepGraph:
        management = ProductManagementSubagent(request.name, self._gateway).as_step()
        pricing = PricingSubagent(self._gateway, self._connectors).as_step()
        filing = ComplianceFilingGateSubagent(
            request.name, request.filing_token, self._connectors
        ).as_step()
        launch = LaunchSubagent(
            request.name, self._guardrails, correlation_id=self._correlation_id
        ).as_step()
        return sequential([management, pricing, filing, launch])


class ProductCommercialOrchestrator(BaseOrchestrator[CommercialRequest]):
    """Parallel post-launch commercial loop (onboarding KYC-gated)."""

    group = "product"
    mode = OrchestrationMode.PARALLEL

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

    def build_graph(self, request: CommercialRequest) -> StepGraph:
        return parallel(
            [
                SalesDistributionSubagent(self._gateway).as_step(),
                ClientOnboardingSubagent(
                    request.client_id,
                    request.kyc_token,
                    self._guardrails,
                    self._connectors,
                    self._gateway,
                    correlation_id=self._correlation_id,
                ).as_step(),
                ClientServicesSubagent(self._gateway).as_step(),
            ]
        )
