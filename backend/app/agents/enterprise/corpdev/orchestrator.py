"""Corp Dev & Strategy orchestrators.

:class:`CorpDevDealOrchestrator` builds the **hybrid** deal graph documented in
``claude1.md`` §8: a sequential spine ``pipeline-sourcing`` -> a PARALLEL pair
(``valuation-modelling`` ‖ ``due-diligence``) -> a fan-in to ``deal-materials``.

:class:`CorpDevStandingOrchestrator` runs the two independent standing lanes
(``strategy-analysis`` ‖ ``investor-relations``) as a **parallel** standalone path
(``POST /agents/corpdev/ir/earnings-pack``).
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
    parallel,
)
from app.agents.enterprise.corpdev.schemas import DealRequest, EarningsPackRequest
from app.agents.enterprise.corpdev.subagents import (
    DealMaterialsSubagent,
    DueDiligenceSubagent,
    InvestorRelationsSubagent,
    PipelineSourcingSubagent,
    StrategyAnalysisSubagent,
    ValuationModellingSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class CorpDevDealOrchestrator(BaseOrchestrator[DealRequest]):
    """Hybrid deal-evaluation orchestrator for Corp Dev."""

    group = "corpdev"
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

    def build_graph(self, request: DealRequest) -> StepGraph:
        sourcing = PipelineSourcingSubagent(
            request.targets, self._gateway, self._connectors
        ).as_step()
        valuation = ValuationModellingSubagent(
            request.ebitda_multiple, request.synergy_rate, self._gateway, self._connectors
        ).as_step(depends_on=("pipeline-sourcing",))
        diligence = DueDiligenceSubagent(self._gateway, self._connectors).as_step(
            depends_on=("pipeline-sourcing",)
        )
        materials = DealMaterialsSubagent(
            self._guardrails, self._gateway, correlation_id=self._correlation_id
        ).as_step(depends_on=("valuation-modelling", "due-diligence"))
        return hybrid([sourcing, valuation, diligence, materials])


class CorpDevStandingOrchestrator(BaseOrchestrator[EarningsPackRequest]):
    """Parallel standing path: strategy-analysis ‖ investor-relations."""

    group = "corpdev"
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

    def build_graph(self, request: EarningsPackRequest) -> StepGraph:
        strategy = StrategyAnalysisSubagent(
            request.segments, self._gateway, self._connectors
        ).as_step()
        ir = InvestorRelationsSubagent(
            request.period,
            self._guardrails,
            self._gateway,
            self._connectors,
            correlation_id=self._correlation_id,
        ).as_step()
        return parallel([strategy, ir])
