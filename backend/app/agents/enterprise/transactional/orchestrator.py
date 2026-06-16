"""Transactional / Operational Finance orchestrators.

:class:`TransactionalOrchestrator` builds the operational cycle documented in
``claude1.md`` §4: four independent lane roots (``accounts-payable`` ‖ ``payroll``
‖ ``procurement`` ‖ ``billing``) with a single local O2C sequence
(``billing -> accounts-receivable -> collections``). Structurally a **hybrid** DAG.

:class:`ApPaymentRunOrchestrator` is the standalone AP payment run
(``POST /agents/transactional/ap/run``): a pure **parallel** per-vendor 3-way match.
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
from app.agents.enterprise.transactional.schemas import CycleRequest, PaymentRunRequest
from app.agents.enterprise.transactional.subagents import (
    AccountsPayableSubagent,
    AccountsReceivableSubagent,
    BillingSubagent,
    CollectionsSubagent,
    InvoiceMatchSubagent,
    PayrollSubagent,
    ProcurementSubagent,
)
from app.connectors import ToolRegistry
from app.guardrails import GuardrailEngine


class TransactionalOrchestrator(BaseOrchestrator[CycleRequest]):
    """Hybrid operational cycle: parallel lanes + one local O2C sequence."""

    group = "transactional"
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

    def build_graph(self, request: CycleRequest) -> StepGraph:
        ap = AccountsPayableSubagent(
            request.vendors,
            self._gateway,
            self._connectors,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step()
        payroll = PayrollSubagent(
            request.employees,
            self._gateway,
            self._connectors,
            self._guardrails,
            correlation_id=self._correlation_id,
        ).as_step()
        procurement = ProcurementSubagent(self._gateway, self._connectors).as_step()

        billing = BillingSubagent(request.customers, self._gateway, self._connectors).as_step()
        ar = AccountsReceivableSubagent(request.customers, self._gateway, self._connectors).as_step(
            depends_on=("billing",)
        )
        collections = CollectionsSubagent(self._gateway).as_step(
            depends_on=("accounts-receivable",)
        )

        return hybrid([ap, payroll, procurement, billing, ar, collections])


class ApPaymentRunOrchestrator(BaseOrchestrator[PaymentRunRequest]):
    """Standalone AP payment run: a pure parallel per-vendor 3-way match fan-out."""

    group = "transactional"
    mode = OrchestrationMode.PARALLEL

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

    def build_graph(self, request: PaymentRunRequest) -> StepGraph:
        steps = [
            InvoiceMatchSubagent(
                v,
                self._gateway,
                self._connectors,
                self._guardrails,
                correlation_id=self._correlation_id,
            ).as_step()
            for v in request.vendors
        ]
        return parallel(steps)
