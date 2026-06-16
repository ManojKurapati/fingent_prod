"""Quant/Data/Tech orchestrators.

:class:`QuantResearchOrchestrator` builds the **parallel** research fan-out
(``claude2.md`` §11): six independent workstreams with no edges.

:class:`QuantPromoteOrchestrator` builds the **sequential** promotion path:
``model-validation -> promote`` — the mandatory model-validation gate precedes
the consequential promotion (research -> validation -> production is ordered).
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
from app.agents.financial_services.quantitative_data_technology.schemas import (
    PromoteRequest,
    QuantJobsRequest,
)
from app.agents.financial_services.quantitative_data_technology.subagents import (
    DataScienceSubagent,
    FinancialEngineeringSubagent,
    ModelValidationGateSubagent,
    PromoteSubagent,
    QuantPricingSubagent,
    QuantResearchSubagent,
    RiskModelDevSubagent,
    SystematicDevSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class QuantResearchOrchestrator(BaseOrchestrator[QuantJobsRequest]):
    """Parallel research/calibration fan-out across the six workstreams."""

    group = "quant"
    mode = OrchestrationMode.PARALLEL

    def __init__(self, *, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    def build_graph(self, request: QuantJobsRequest) -> StepGraph:
        return parallel(
            [
                QuantPricingSubagent(self._gateway).as_step(),
                QuantResearchSubagent(self._gateway).as_step(),
                RiskModelDevSubagent(self._gateway).as_step(),
                DataScienceSubagent(self._gateway).as_step(),
                FinancialEngineeringSubagent(self._gateway).as_step(),
                SystematicDevSubagent(self._gateway).as_step(),
            ]
        )


class QuantPromoteOrchestrator(BaseOrchestrator[PromoteRequest]):
    """Sequential validation-gated promotion to production."""

    group = "quant"
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

    def build_graph(self, request: PromoteRequest) -> StepGraph:
        validation = ModelValidationGateSubagent(
            request.model_id, request.validation_token, self._connectors
        ).as_step()
        promote = PromoteSubagent(
            request.model_id, self._guardrails, correlation_id=self._correlation_id
        ).as_step()
        return sequential([validation, promote])
