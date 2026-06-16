"""FP&A orchestrators.

:class:`FpaOrchestrator` builds the **hybrid** planning graph documented in
``claude1.md`` §2: a sequential spine ``data-intake -> budget-consolidation``, a
PARALLEL fan-out (``forecast-engine`` ‖ ``variance:<cc>`` ‖ ``revenue-analytics``
‖ ``scenario-modelling``), then a fan-in to ``reporting-packs``.

:class:`FpaScenarioOrchestrator` is the standalone scenario path
(``POST /agents/fpa/scenario``): a short **sequential** chain
``data-intake -> scenario-modelling``.
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
from app.agents.enterprise.fpa.schemas import ForecastRequest, ScenarioRequest
from app.agents.enterprise.fpa.subagents import (
    BudgetConsolidationSubagent,
    DataIntakeSubagent,
    ForecastEngineSubagent,
    ReportingPacksSubagent,
    RevenueAnalyticsSubagent,
    ScenarioModellingSubagent,
    VarianceSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class FpaOrchestrator(BaseOrchestrator[ForecastRequest]):
    """Hybrid planning orchestrator for FP&A."""

    group = "fpa"
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

    def build_graph(self, request: ForecastRequest) -> StepGraph:
        ccs = request.cost_centres
        intake = DataIntakeSubagent(request.period, ccs, self._gateway, self._connectors).as_step()
        consolidation = BudgetConsolidationSubagent(ccs, self._gateway, self._connectors).as_step(
            depends_on=("data-intake",)
        )

        forecast = ForecastEngineSubagent(ccs, self._gateway).as_step(
            depends_on=("budget-consolidation",)
        )
        revenue = RevenueAnalyticsSubagent(ccs, self._gateway).as_step(
            depends_on=("budget-consolidation",)
        )
        scenario = ScenarioModellingSubagent(request.period, {}, self._gateway).as_step(
            depends_on=("data-intake",)
        )
        variances = [
            VarianceSubagent(
                cc,
                self._guardrails,
                threshold=request.variance_threshold,
                correlation_id=self._correlation_id,
            ).as_step(depends_on=("data-intake", "budget-consolidation"))
            for cc in ccs
        ]

        fanout = [forecast, revenue, scenario, *variances]
        report = ReportingPacksSubagent().as_step(depends_on=tuple(s.name for s in fanout))
        return hybrid([intake, consolidation, *fanout, report])


class FpaScenarioOrchestrator(BaseOrchestrator[ScenarioRequest]):
    """Standalone scenario/sensitivity path: sequential intake -> modelling."""

    group = "fpa"
    mode = OrchestrationMode.SEQUENTIAL

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

    def build_graph(self, request: ScenarioRequest) -> StepGraph:
        intake = DataIntakeSubagent(
            request.period, request.cost_centres, self._gateway, self._connectors
        ).as_step()
        scenario = ScenarioModellingSubagent(
            request.period, request.drivers, self._gateway
        ).as_step()
        return sequential([intake, scenario])
