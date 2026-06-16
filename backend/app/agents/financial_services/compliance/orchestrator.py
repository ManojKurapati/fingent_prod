"""Compliance orchestrators (per ``claude2.md`` §9).

* :class:`ComplianceScreenOrchestrator` — **hybrid**: ``aml-kyc`` ‖
  ``sanctions-screening`` fan out and join at ``fraud-investigation`` (the
  sequential disposition that clears or escalates).
* :class:`ComplianceContinuousOrchestrator` — **parallel**: ``compliance-monitoring``
  ‖ ``regulatory-affairs`` ‖ ``legal-counsel`` standing functions.
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
from app.agents.financial_services.compliance.schemas import ContinuousRequest, ScreenRequest
from app.agents.financial_services.compliance.subagents import (
    AmlKycSubagent,
    ComplianceMonitoringSubagent,
    FraudInvestigationSubagent,
    LegalCounselSubagent,
    RegulatoryAffairsSubagent,
    SanctionsScreeningSubagent,
)
from app.connectors import ToolRegistry


class ComplianceScreenOrchestrator(BaseOrchestrator[ScreenRequest]):
    """Hybrid screening orchestrator: parallel screens -> disposition join."""

    group = "compliance"
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

    def build_graph(self, request: ScreenRequest) -> StepGraph:
        aml = AmlKycSubagent(request.subject, self._gateway, self._connectors).as_step()
        sanctions = SanctionsScreeningSubagent(
            request.subject, self._gateway, self._connectors
        ).as_step()
        disposition = FraudInvestigationSubagent().as_step(
            depends_on=("aml-kyc", "sanctions-screening")
        )
        return hybrid([aml, sanctions, disposition])


class ComplianceContinuousOrchestrator(BaseOrchestrator[ContinuousRequest]):
    """Parallel continuous-functions orchestrator."""

    group = "compliance"
    mode = OrchestrationMode.PARALLEL

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

    def build_graph(self, request: ContinuousRequest) -> StepGraph:
        monitoring = ComplianceMonitoringSubagent(self._gateway, self._connectors).as_step()
        regulatory = RegulatoryAffairsSubagent(self._gateway, self._connectors).as_step()
        legal = LegalCounselSubagent(self._gateway, self._connectors).as_step()
        return parallel([monitoring, regulatory, legal])
