"""Accounting & Controllership orchestrator.

:class:`AccountingCloseOrchestrator` builds the **hybrid** close graph documented
in ``claude1.md`` §3: ``close-orchestration`` opens the period, a PARALLEL
sub-ledger fan-out (``journal-entries`` ‖ ``fixed-assets`` ‖ ``cost-inventory`` ‖
``technical-accounting``) fans in to ``reconciliations``, and ``consolidations``
is sequenced strictly last (all entity books must close before consolidation).
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
)
from app.agents.enterprise.accounting.schemas import CloseRequest
from app.agents.enterprise.accounting.subagents import (
    CloseOrchestrationSubagent,
    ConsolidationsSubagent,
    CostInventorySubagent,
    FixedAssetsSubagent,
    JournalEntriesSubagent,
    ReconciliationsSubagent,
    TechnicalAccountingSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class AccountingCloseOrchestrator(BaseOrchestrator[CloseRequest]):
    """Hybrid period-close orchestrator for Accounting & Controllership."""

    group = "accounting"
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

    def build_graph(self, request: CloseRequest) -> StepGraph:
        entities = request.entities
        close = CloseOrchestrationSubagent(request.period, entities, self._gateway).as_step()

        journals = JournalEntriesSubagent(
            entities,
            self._gateway,
            self._connectors,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step(depends_on=("close-orchestration",))
        assets = FixedAssetsSubagent(entities, self._gateway, self._connectors).as_step(
            depends_on=("close-orchestration",)
        )
        inventory = CostInventorySubagent(entities, self._gateway, self._connectors).as_step(
            depends_on=("close-orchestration",)
        )
        technical = TechnicalAccountingSubagent(entities, self._gateway, self._connectors).as_step(
            depends_on=("close-orchestration",)
        )

        subledgers = [journals, assets, inventory, technical]
        recon = ReconciliationsSubagent(self._gateway, self._connectors).as_step(
            depends_on=tuple(s.name for s in subledgers)
        )
        consol = ConsolidationsSubagent(entities, self._gateway, self._connectors).as_step(
            depends_on=("reconciliations",)
        )
        return hybrid([close, *subledgers, recon, consol])
