"""Concrete cross-agent chains.

* :func:`build_cfo_enterprise_chain` — the Leadership/CFO agent invoking another
  enterprise agent: FP&A produces the forecast, then Leadership assembles the
  board pack from it. Demonstrates one agent orchestrating another.
* :func:`build_fs_trade_chain` — the financial-services flow
  ``research -> portfolio -> trading -> operations``, each link consuming the
  prior agent's output, with every consequential action gated.

Both return a list of :class:`ChainStep` to feed :func:`app.integration.chain.run_chain`.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.agents.core import ClaudeGateway, RunResult
from app.agents.enterprise.fpa.orchestrator import FpaOrchestrator
from app.agents.enterprise.fpa.schemas import ForecastRequest
from app.agents.enterprise.leadership.orchestrator import LeadershipOrchestrator
from app.agents.enterprise.leadership.schemas import BoardPackRequest
from app.agents.financial_services.asset_investment_management.orchestrator import (
    AimRebalanceOrchestrator,
)
from app.agents.financial_services.asset_investment_management.schemas import RebalanceRequest
from app.agents.financial_services.operations_middle_back_office.orchestrator import (
    OpsPipelineOrchestrator,
)
from app.agents.financial_services.operations_middle_back_office.schemas import TradeProcessRequest
from app.agents.financial_services.quantitative_data_technology.orchestrator import (
    QuantResearchOrchestrator,
)
from app.agents.financial_services.quantitative_data_technology.schemas import QuantJobsRequest
from app.agents.financial_services.sales_trading_markets.orchestrator import (
    SalesTradingOrchestrator,
)
from app.agents.financial_services.sales_trading_markets.schemas import OrderRequest
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine
from app.integration.chain import ChainStep


def build_cfo_enterprise_chain(
    *,
    gateway: ClaudeGateway,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    period: str,
    cost_centres: list[str],
    divisions: list[str],
    target_leverage: float = 0.4,
    correlation_id: str | None = None,
) -> list[ChainStep]:
    """CFO invokes FP&A, then assembles the Leadership board pack from its output."""
    fpa = FpaOrchestrator(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        correlation_id=correlation_id,
    )
    leadership = LeadershipOrchestrator(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        correlation_id=correlation_id,
    )

    def _forecast_request(_results: Mapping[str, RunResult]) -> ForecastRequest:
        return ForecastRequest(period=period, cost_centres=cost_centres)

    def _board_request(results: Mapping[str, RunResult]) -> BoardPackRequest:
        # Consume the FP&A run: the CFO only builds the board pack once the forecast
        # has been produced (its outputs are present in ``results``).
        assert results["fpa"].outputs, "leadership requires the FP&A forecast first"
        return BoardPackRequest(period=period, divisions=divisions, target_leverage=target_leverage)

    return [
        ChainStep("fpa", fpa, _forecast_request),
        ChainStep("leadership", leadership, _board_request),
    ]


def build_fs_trade_chain(
    *,
    gateway: ClaudeGateway,
    guardrails: GuardrailEngine,
    connectors: ToolRegistry,
    dataset: str,
    portfolio_id: str,
    names: list[str],
    account: str,
    book: str,
    correlation_id: str | None = None,
) -> list[ChainStep]:
    """research -> portfolio -> trading -> operations, threading each output forward."""
    research = QuantResearchOrchestrator(gateway=gateway)
    portfolio = AimRebalanceOrchestrator(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        correlation_id=correlation_id,
    )
    trading = SalesTradingOrchestrator(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        correlation_id=correlation_id,
    )
    operations = OpsPipelineOrchestrator(
        gateway=gateway,
        guardrails=guardrails,
        connectors=connectors,
        correlation_id=correlation_id,
    )

    instrument = names[0]
    order_id = f"ord-{portfolio_id}"

    def _research_request(_results: Mapping[str, RunResult]) -> QuantJobsRequest:
        return QuantJobsRequest(dataset=dataset)

    def _portfolio_request(results: Mapping[str, RunResult]) -> RebalanceRequest:
        assert results["research"].outputs, "portfolio requires research output first"
        return RebalanceRequest(portfolio_id=portfolio_id, names=names)

    def _trading_request(results: Mapping[str, RunResult]) -> OrderRequest:
        # Size the order from the portfolio's approved target notional.
        target_notional: float = results["portfolio"].outputs["mandate-risk-gate"][
            "target_notional"
        ]
        return OrderRequest(
            order_id=order_id,
            account=account,
            instrument=instrument,
            side="buy",
            quantity=max(target_notional, 1.0),
            book=book,
        )

    def _operations_request(results: Mapping[str, RunResult]) -> TradeProcessRequest:
        # The trade flows from the routed order; settle the executed notional.
        gate = results["trading"].outputs["pre-trade-risk-gate"]
        return TradeProcessRequest(trade_id=order_id, amount=float(gate["notional"]))

    return [
        ChainStep("research", research, _research_request),
        ChainStep("portfolio", portfolio, _portfolio_request),
        ChainStep("trading", trading, _trading_request),
        ChainStep("operations", operations, _operations_request),
    ]
