"""Finance Systems & Operations orchestrators.

:class:`FinOpsOrchestrator` builds the **hybrid** operations graph documented in
``claude1.md`` §9: a sequential spine ``data-pipelines -> dashboards-reporting``
plus three independent parallel lanes (``erp-administration`` ‖
``process-transformation`` ‖ ``o2c-p2p-process-owner``).

:class:`FinOpsAccessChangeOrchestrator` is the standalone, SoD-gated access-change
path (``POST /agents/finops/erp/access-change``): a single ``erp-administration``
step run as a SEQUENTIAL graph.
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
from app.agents.enterprise.finops.schemas import AccessChangeRequest, OperationsRequest
from app.agents.enterprise.finops.subagents import (
    DashboardsReportingSubagent,
    DataPipelinesSubagent,
    ErpAdministrationSubagent,
    O2cP2pProcessOwnerSubagent,
    ProcessTransformationSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class FinOpsOrchestrator(BaseOrchestrator[OperationsRequest]):
    """Hybrid operations orchestrator: data spine + independent parallel lanes."""

    group = "finops"
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

    def build_graph(self, request: OperationsRequest) -> StepGraph:
        pipelines = DataPipelinesSubagent(
            request.sources, self._gateway, self._connectors
        ).as_step()
        dashboards = DashboardsReportingSubagent(self._gateway).as_step(
            depends_on=("data-pipelines",)
        )
        erp = ErpAdministrationSubagent(
            request.access_changes,
            self._gateway,
            self._guardrails,
            self._connectors,
            correlation_id=self._correlation_id,
        ).as_step()
        transformation = ProcessTransformationSubagent(self._gateway, self._connectors).as_step()
        o2c = O2cP2pProcessOwnerSubagent(self._gateway, self._connectors).as_step()
        return hybrid([pipelines, dashboards, erp, transformation, o2c])


class FinOpsAccessChangeOrchestrator(BaseOrchestrator[AccessChangeRequest]):
    """Standalone SoD-gated access-change path: a single sequential erp step."""

    group = "finops"
    mode = OrchestrationMode.SEQUENTIAL

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

    def build_graph(self, request: AccessChangeRequest) -> StepGraph:
        erp = ErpAdministrationSubagent(
            [request.change],
            self._gateway,
            self._guardrails,
            self._connectors,
            correlation_id=self._correlation_id,
        ).as_step()
        return sequential([erp])
