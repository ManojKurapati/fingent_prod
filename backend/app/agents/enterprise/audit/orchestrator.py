"""Internal Audit & Controls orchestrator.

:class:`AuditEngagementOrchestrator` builds the sequenced engagement documented in
``claude1.md`` §7. The macro-flow is **sequential** —
``audit-planning -> testing -> findings-reporting -> remediation-tracking`` — but
the **testing stage fans out** (``control-test:<id>`` ‖ ``sox-controls``), so the
graph is realised as a HYBRID DAG whose spine ordering is asserted in tests.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.enterprise.audit.schemas import EngagementRequest
from app.agents.enterprise.audit.subagents import (
    AuditPlanningSubagent,
    ControlTestSubagent,
    FindingsReportingSubagent,
    RemediationTrackingSubagent,
    SoxControlsSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class AuditEngagementOrchestrator(BaseOrchestrator[EngagementRequest]):
    """Sequenced audit engagement with a parallel testing stage (hybrid DAG)."""

    group = "audit"
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

    def build_graph(self, request: EngagementRequest) -> StepGraph:
        controls = request.controls
        planning = AuditPlanningSubagent(request.engagement, controls, self._gateway).as_step()

        control_tests = [
            ControlTestSubagent(c, self._gateway, self._connectors).as_step(
                depends_on=("audit-planning",)
            )
            for c in controls
        ]
        sox = SoxControlsSubagent(controls, self._gateway, self._connectors).as_step(
            depends_on=("audit-planning",)
        )
        testing = [*control_tests, sox]

        findings = FindingsReportingSubagent(
            request.engagement, self._guardrails, correlation_id=self._correlation_id
        ).as_step(depends_on=tuple(s.name for s in testing))
        remediation = RemediationTrackingSubagent().as_step(depends_on=("findings-reporting",))

        return hybrid([planning, *testing, findings, remediation])
