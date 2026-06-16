"""Risk Management orchestrator (per ``claude2.md`` §8).

:class:`RiskRunOrchestrator` realises the parallel fan-out into a sequential
aggregation tail: the four risk-type measures plus the independent
``model-validation`` assurance run concurrently against one snapshot, then
``erm-aggregation`` is the barrier that joins on all of them. Because a strictly
PARALLEL graph cannot carry a dependent tail, the graph mode is HYBRID; tests
assert both the concurrency of the measures and that aggregation joins last.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.financial_services.risk.schemas import RiskRunRequest
from app.agents.financial_services.risk.subagents import (
    CreditRiskSubagent,
    ErmAggregationSubagent,
    LiquidityRiskSubagent,
    MarketRiskSubagent,
    ModelValidationSubagent,
    OperationalRiskSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class RiskRunOrchestrator(BaseOrchestrator[RiskRunRequest]):
    """Hybrid enterprise-risk orchestrator: parallel measures -> aggregation."""

    group = "risk"
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

    def build_graph(self, request: RiskRunRequest) -> StepGraph:
        book = request.book
        measures = [
            MarketRiskSubagent(book, self._gateway, self._connectors).as_step(),
            CreditRiskSubagent(book, self._gateway, self._connectors).as_step(),
            OperationalRiskSubagent(book, self._gateway, self._connectors).as_step(),
            LiquidityRiskSubagent(book, self._gateway, self._connectors).as_step(),
            ModelValidationSubagent(book, self._gateway, self._connectors).as_step(),
        ]
        aggregation = ErmAggregationSubagent(
            self._guardrails, correlation_id=self._correlation_id
        ).as_step(depends_on=tuple(s.name for s in measures))
        return hybrid([*measures, aggregation])
