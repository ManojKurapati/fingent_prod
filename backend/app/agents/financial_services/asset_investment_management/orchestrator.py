"""Asset & Investment Management orchestrators.

:class:`AimRebalanceOrchestrator` builds the **hybrid** rebalance graph from
``claude2.md`` §3: a sequential ``macro-strategy -> asset-allocation`` spine ‖ a
PARALLEL ``research:<name>`` fan-out, joined at ``portfolio-construction``, then a
MANDATORY ``mandate-risk-gate`` before gated ``buyside-execution``.

:class:`AimResearchOrchestrator` is the standalone PARALLEL research fan-out
(``POST /agents/asset-investment-management/research``).
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
from app.agents.financial_services.asset_investment_management.schemas import (
    RebalanceRequest,
    ResearchRequest,
)
from app.agents.financial_services.asset_investment_management.subagents import (
    AssetAllocationSubagent,
    BuysideExecutionSubagent,
    BuysideResearchSubagent,
    MacroStrategySubagent,
    MandateRiskGateSubagent,
    PortfolioConstructionSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class AimRebalanceOrchestrator(BaseOrchestrator[RebalanceRequest]):
    """Hybrid orchestrator for a portfolio rebalance."""

    group = "asset-investment-management"
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

    def build_graph(self, request: RebalanceRequest) -> StepGraph:
        macro = MacroStrategySubagent(self._gateway).as_step()
        allocation = AssetAllocationSubagent(self._gateway).as_step(depends_on=("macro-strategy",))
        research = [
            BuysideResearchSubagent(name, self._gateway).as_step() for name in request.names
        ]
        construction = PortfolioConstructionSubagent(
            request.portfolio_id, request.names, self._gateway, self._connectors
        ).as_step(depends_on=("asset-allocation", *(s.name for s in research)))
        gate = MandateRiskGateSubagent(
            request.portfolio_id, self._gateway, self._connectors
        ).as_step(depends_on=("portfolio-construction",))
        execution = BuysideExecutionSubagent(
            request.portfolio_id, self._guardrails, correlation_id=self._correlation_id
        ).as_step(depends_on=("mandate-risk-gate",))
        return hybrid([macro, allocation, *research, construction, gate, execution])


class AimResearchOrchestrator(BaseOrchestrator[ResearchRequest]):
    """Standalone parallel research fan-out: one independent worker per name."""

    group = "asset-investment-management"
    mode = OrchestrationMode.PARALLEL

    def __init__(self, *, gateway: ClaudeGateway, correlation_id: str | None = None) -> None:
        self._gateway = gateway
        self._correlation_id = correlation_id

    def build_graph(self, request: ResearchRequest) -> StepGraph:
        return parallel(
            [BuysideResearchSubagent(name, self._gateway).as_step() for name in request.names]
        )
