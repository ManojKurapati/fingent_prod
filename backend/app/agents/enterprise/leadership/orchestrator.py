"""Leadership orchestrators.

:class:`LeadershipOrchestrator` builds the **hybrid** synthesis graph documented in
``claude1.md`` §1: a sequential spine ``divisional-rollup -> capital-strategy``, a
PARALLEL fan-out where the independent standing lanes (``capital-strategy`` ‖
``budget-plan-signoff`` ‖ ``transformation-sponsor``) all gate only on the
consolidation, then ``board-investor-reporting`` as a partial fan-in.

:class:`LeadershipCapitalOrchestrator` is the standalone capital-scenario path
(``POST /agents/leadership/capital-scenario``): a short **sequential** chain
``divisional-rollup -> capital-strategy``.
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
from app.agents.enterprise.leadership.schemas import BoardPackRequest, CapitalScenarioRequest
from app.agents.enterprise.leadership.subagents import (
    BoardInvestorReportingSubagent,
    BudgetPlanSignoffSubagent,
    CapitalStrategySubagent,
    DivisionalRollupSubagent,
    TransformationSponsorSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class LeadershipOrchestrator(BaseOrchestrator[BoardPackRequest]):
    """Hybrid board-pack synthesis orchestrator for Leadership."""

    group = "leadership"
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

    def build_graph(self, request: BoardPackRequest) -> StepGraph:
        divisions = request.divisions
        rollup = DivisionalRollupSubagent(divisions, self._gateway, self._connectors).as_step()
        capital = CapitalStrategySubagent(
            request.target_leverage, self._gateway, self._connectors
        ).as_step(depends_on=("divisional-rollup",))
        budget = BudgetPlanSignoffSubagent(
            self._gateway,
            self._connectors,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step(depends_on=("divisional-rollup",))
        transform = TransformationSponsorSubagent(self._connectors, self._gateway).as_step(
            depends_on=("divisional-rollup",)
        )
        board = BoardInvestorReportingSubagent(
            request.period,
            self._guardrails,
            self._gateway,
            correlation_id=self._correlation_id,
        ).as_step(depends_on=("divisional-rollup", "capital-strategy"))
        return hybrid([rollup, capital, budget, transform, board])


class LeadershipCapitalOrchestrator(BaseOrchestrator[CapitalScenarioRequest]):
    """Standalone capital-structure path: sequential rollup -> capital strategy."""

    group = "leadership"
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

    def build_graph(self, request: CapitalScenarioRequest) -> StepGraph:
        rollup = DivisionalRollupSubagent(
            request.divisions, self._gateway, self._connectors
        ).as_step()
        capital = CapitalStrategySubagent(
            request.target_leverage, self._gateway, self._connectors
        ).as_step()
        return sequential([rollup, capital])
