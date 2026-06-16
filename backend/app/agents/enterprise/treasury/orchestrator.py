"""Treasury daily-position orchestrator.

:class:`TreasuryDailyPositionOrchestrator` realises the flow documented in
``claude1.md`` §5: a **sequential spine** ``cash-positioning ->
liquidity-forecasting`` with a **parallel tail** (``fx-hedging`` ‖
``debt-covenants``, both consuming the forecast) and ``bank-connectivity`` as an
independent standing service running alongside.

The spec labels the orchestration "Sequential" for its dependency chain; because
a strictly-linear SEQUENTIAL graph cannot carry a parallel tail, the graph mode is
HYBRID. Tests assert both the spine ordering and the concurrent tail, so the
documented dependency semantics are honoured exactly. The daily run is read-only;
the consequential hedge/sweep executions are gated separately (see ``router.py``).
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.enterprise.treasury.schemas import DailyPositionRequest
from app.agents.enterprise.treasury.subagents import (
    BankConnectivitySubagent,
    CashPositioningSubagent,
    DebtCovenantsSubagent,
    FxHedgingSubagent,
    LiquidityForecastingSubagent,
)
from app.connectors import ToolRegistry

# Standard FX exposure basket monitored on every daily run.
_FX_BASKET = ("EUR", "GBP", "JPY")


class TreasuryDailyPositionOrchestrator(BaseOrchestrator[DailyPositionRequest]):
    """Hybrid daily-position orchestrator (sequential spine + parallel tail)."""

    group = "treasury"
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

    def build_graph(self, request: DailyPositionRequest) -> StepGraph:
        cash = CashPositioningSubagent(request.accounts, self._gateway, self._connectors).as_step()
        liquidity = LiquidityForecastingSubagent(self._gateway, self._connectors).as_step(
            depends_on=("cash-positioning",)
        )
        fx = FxHedgingSubagent(list(_FX_BASKET), self._gateway, self._connectors).as_step(
            depends_on=("liquidity-forecasting",)
        )
        covenants = DebtCovenantsSubagent(self._gateway, self._connectors).as_step(
            depends_on=("liquidity-forecasting",)
        )
        # bank-connectivity is a standing service: independent, runs in parallel.
        bank = BankConnectivitySubagent(self._gateway, self._connectors).as_step()
        return hybrid([cash, liquidity, fx, covenants, bank])
