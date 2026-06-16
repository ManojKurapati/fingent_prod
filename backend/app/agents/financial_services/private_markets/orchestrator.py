"""Private Markets orchestrators.

:class:`PrivateMarketsOrchestrator` builds the **hybrid** lifecycle graph from
``claude2.md`` §4: ``origination-pipeline`` (head) → a PARALLEL diligence fan-out
(``diligence:financials`` ‖ ``diligence:legal`` ‖ ``diligence:market``) → exactly
one asset-class underwriting subagent (selected by ``asset_class``) → ``ic-commitment``,
which holds the capital commitment for the Investment Committee approval gate.

:class:`StewardshipOrchestrator` is the standalone post-close monitor
(``POST /agents/private-markets/monitor``): a short **sequential** chain.
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
from app.agents.financial_services.private_markets.schemas import (
    AssetClass,
    DealRequest,
    MonitorRequest,
)
from app.agents.financial_services.private_markets.subagents import (
    CreditUnderwritingSubagent,
    DiligenceSubagent,
    FundOfFundsSubagent,
    IcCommitmentSubagent,
    OriginationPipelineSubagent,
    PeVcUnderwritingSubagent,
    PortfolioStewardshipSubagent,
    RealAssetUnderwritingSubagent,
    _UnderwritingSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine

_DILIGENCE_WORKSTREAMS = ("financials", "legal", "market")

_UNDERWRITERS: dict[AssetClass, type[_UnderwritingSubagent]] = {
    "pe_vc": PeVcUnderwritingSubagent,
    "credit": CreditUnderwritingSubagent,
    "real_asset": RealAssetUnderwritingSubagent,
    "fund_of_funds": FundOfFundsSubagent,
}


class PrivateMarketsOrchestrator(BaseOrchestrator[DealRequest]):
    """Hybrid underwriting orchestrator for Private Markets."""

    group = "private-markets"
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
        deal = request.deal_id
        origination = OriginationPipelineSubagent(
            deal, request.asset_class, self._gateway
        ).as_step()
        diligence = [
            DiligenceSubagent(ws, deal, self._gateway, self._connectors).as_step(
                depends_on=("origination-pipeline",)
            )
            for ws in _DILIGENCE_WORKSTREAMS
        ]
        underwriting = _UNDERWRITERS[request.asset_class](
            deal, self._gateway, self._connectors
        ).as_step(depends_on=tuple(s.name for s in diligence))
        commitment = IcCommitmentSubagent(
            deal, self._guardrails, correlation_id=self._correlation_id
        ).as_step(depends_on=(underwriting.name,))
        return hybrid([origination, *diligence, underwriting, commitment])


class StewardshipOrchestrator(BaseOrchestrator[MonitorRequest]):
    """Standalone post-close stewardship monitor: a single sequential step."""

    group = "private-markets"
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

    def build_graph(self, request: MonitorRequest) -> StepGraph:
        stewardship = PortfolioStewardshipSubagent(
            request.portfolio_id, self._gateway, self._connectors
        ).as_step()
        return sequential([stewardship])
