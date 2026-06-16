"""Sales & Trading / Markets orchestrator.

Builds the **hybrid** desk graph documented in ``claude2.md`` §2: four parallel
feeds (``sales-coverage`` ‖ ``pricing-quoting`` ‖ ``quant-signals`` ‖
``structuring``) fan in to the MANDATORY sequential ``pre-trade-risk-gate``;
``execution-algo`` routes only behind a cleared gate; ``risk-hedging`` re-hedges
post-fill.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.financial_services.sales_trading_markets.schemas import OrderRequest
from app.agents.financial_services.sales_trading_markets.subagents import (
    ExecutionAlgoSubagent,
    PreTradeRiskGateSubagent,
    PricingQuotingSubagent,
    QuantSignalsSubagent,
    RiskHedgingSubagent,
    SalesCoverageSubagent,
    StructuringSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine

_FEEDS = ("sales-coverage", "pricing-quoting", "quant-signals", "structuring")


class SalesTradingOrchestrator(BaseOrchestrator[OrderRequest]):
    """Hybrid orchestrator with a hard sequential pre-trade risk gate."""

    group = "sales-trading-markets"
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

    def build_graph(self, request: OrderRequest) -> StepGraph:
        coverage = SalesCoverageSubagent(request.account, self._gateway).as_step()
        pricing = PricingQuotingSubagent(
            request.instrument, self._gateway, self._connectors
        ).as_step()
        signals = QuantSignalsSubagent(request.instrument, self._gateway).as_step()
        structuring = StructuringSubagent(request.instrument, self._gateway).as_step()

        gate = PreTradeRiskGateSubagent(
            request.account,
            request.book,
            request.quantity,
            self._gateway,
            self._connectors,
        ).as_step(depends_on=_FEEDS)
        execution = ExecutionAlgoSubagent(
            request.order_id, self._guardrails, correlation_id=self._correlation_id
        ).as_step(depends_on=("pre-trade-risk-gate",))
        hedging = RiskHedgingSubagent(request.book, self._gateway).as_step(
            depends_on=("execution-algo",)
        )
        return hybrid([coverage, pricing, signals, structuring, gate, execution, hedging])
