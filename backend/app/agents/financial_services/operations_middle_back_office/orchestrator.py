"""Operations orchestrators.

:class:`OpsPipelineOrchestrator` builds the **hybrid** processing pipeline
(``claude2.md`` §10): a sequential spine ``trade-support -> settlements`` (you
cannot settle an unconfirmed trade) feeding a PARALLEL reconciliation layer
(``reconciliations`` ‖ ``fund-accounting`` ‖ ``custody-ops`` ‖ ``collateral-mgmt``).

:class:`OpsReconOrchestrator` is the standalone nightly reconciliation run: a
PARALLEL fan-out over the same four surfaces with no spine.
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
from app.agents.financial_services.operations_middle_back_office.schemas import (
    OpsReconRequest,
    TradeProcessRequest,
)
from app.agents.financial_services.operations_middle_back_office.subagents import (
    CollateralMgmtSubagent,
    CustodyOpsSubagent,
    FundAccountingSubagent,
    ReconciliationsSubagent,
    SettlementsSubagent,
    TradeSupportSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class OpsPipelineOrchestrator(BaseOrchestrator[TradeProcessRequest]):
    """Hybrid confirm -> settle -> reconcile pipeline for one trade."""

    group = "ops"
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

    def build_graph(self, request: TradeProcessRequest) -> StepGraph:
        trade_support = TradeSupportSubagent(
            request.trade_id, self._gateway, self._connectors
        ).as_step()
        settlements = SettlementsSubagent(
            request.trade_id,
            request.amount,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step(depends_on=("trade-support",))

        recon_layer = [
            ReconciliationsSubagent(self._gateway, self._connectors).as_step(
                depends_on=("settlements",)
            ),
            FundAccountingSubagent(self._gateway, self._connectors).as_step(
                depends_on=("settlements",)
            ),
            CustodyOpsSubagent(self._gateway, self._connectors).as_step(
                depends_on=("settlements",)
            ),
            CollateralMgmtSubagent(self._gateway, self._connectors).as_step(
                depends_on=("settlements",)
            ),
        ]
        return hybrid([trade_support, settlements, *recon_layer])


class OpsReconOrchestrator(BaseOrchestrator[OpsReconRequest]):
    """Standalone parallel reconciliation run over settled records."""

    group = "ops"
    mode = OrchestrationMode.PARALLEL

    def __init__(self, *, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    def build_graph(self, request: OpsReconRequest) -> StepGraph:
        return parallel(
            [
                ReconciliationsSubagent(self._gateway, self._connectors).as_step(),
                FundAccountingSubagent(self._gateway, self._connectors).as_step(),
                CustodyOpsSubagent(self._gateway, self._connectors).as_step(),
                CollateralMgmtSubagent(self._gateway, self._connectors).as_step(),
            ]
        )
