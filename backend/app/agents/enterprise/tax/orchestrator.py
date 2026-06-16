"""Tax orchestrators.

:class:`TaxProvisionOrchestrator` builds the **hybrid** provision graph documented
in ``claude1.md`` §6: a PARALLEL fan-out by tax type (``direct-tax-compliance`` ‖
``indirect-tax`` ‖ ``transfer-pricing`` ‖ ``international-tax``) plus a standing
``audit-defence`` stream, fanning in to ``tax-provision``.

:class:`TaxFilingOrchestrator` is the standalone external-filing path
(``POST /agents/tax/file/{return_id}``): a single **sequential** step that gates
the submission through the guardrail engine.
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
from app.agents.enterprise.tax.schemas import FileRequest, ProvisionRequest
from app.agents.enterprise.tax.subagents import (
    AuditDefenceSubagent,
    DirectTaxComplianceSubagent,
    IndirectTaxSubagent,
    InternationalTaxSubagent,
    TaxFilingSubagent,
    TaxProvisionSubagent,
    TransferPricingSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class TaxProvisionOrchestrator(BaseOrchestrator[ProvisionRequest]):
    """Hybrid provision orchestrator: parallel compliance fan-out -> provision fan-in."""

    group = "tax"
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

    def build_graph(self, request: ProvisionRequest) -> StepGraph:
        js = request.jurisdictions
        direct = DirectTaxComplianceSubagent(js, self._gateway, self._connectors).as_step()
        indirect = IndirectTaxSubagent(js, self._gateway, self._connectors).as_step()
        transfer = TransferPricingSubagent(js, self._gateway, self._connectors).as_step()
        international = InternationalTaxSubagent(js, self._gateway, self._connectors).as_step()
        # standing stream — independent, runs alongside, not a provision dependency
        audit_defence = AuditDefenceSubagent(js, self._gateway, self._connectors).as_step()

        provision = TaxProvisionSubagent(self._gateway).as_step(
            depends_on=(
                "direct-tax-compliance",
                "indirect-tax",
                "transfer-pricing",
                "international-tax",
            )
        )
        return hybrid([direct, indirect, transfer, international, audit_defence, provision])


class TaxFilingOrchestrator(BaseOrchestrator[FileRequest]):
    """Standalone external-filing path: a single sequential, gated step."""

    group = "tax"
    mode = OrchestrationMode.SEQUENTIAL

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

    def build_graph(self, request: FileRequest) -> StepGraph:
        filing = TaxFilingSubagent(
            request.return_id,
            request.jurisdiction,
            self._gateway,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step()
        return sequential([filing])
