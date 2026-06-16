"""The template group-agent orchestrator.

Demonstrates the HYBRID shape used by most groups: a sequential head
(``data-intake``), a PARALLEL fan-out (one ``analyze:<cc>`` per cost centre), and
a fan-in tail (``reporting-pack``) that depends on all of them.

COPY THIS FILE. Keep the orchestration choice your group's spec documents
(sequential / parallel / hybrid) and assert it in your tests.
"""

from __future__ import annotations

from app.agents._template.schemas import RunRequest
from app.agents._template.subagents import (
    AnalyzeSubagent,
    IntakeSubagent,
    ReportSubagent,
)
from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.guardrails import GuardrailEngine


class TemplateOrchestrator(BaseOrchestrator[RunRequest]):
    """Group orchestrator for the template agent."""

    group = "template"
    mode = OrchestrationMode.HYBRID

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        guardrails: GuardrailEngine,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._guardrails = guardrails
        self._correlation_id = correlation_id

    def build_graph(self, request: RunRequest) -> StepGraph:
        intake = IntakeSubagent(self._gateway).as_step()
        analyses = [
            AnalyzeSubagent(cc, self._gateway).as_step(depends_on=("data-intake",))
            for cc in request.cost_centres
        ]
        report = ReportSubagent(self._guardrails, correlation_id=self._correlation_id).as_step(
            depends_on=("data-intake", *(s.name for s in analyses))
        )
        return hybrid([intake, *analyses, report])
