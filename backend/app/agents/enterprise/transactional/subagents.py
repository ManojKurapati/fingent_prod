"""Transactional subagents — one stateless worker per responsibility cluster.

Numeric inputs (invoices, POs, payroll, contracts, cash) are pulled from
connectors so the maths is deterministic and testable with fakes; the Claude
gateway is used for the per-lane narrative step. The only **consequential** actions
are cash movements (AP payment runs and payroll disbursement), which are routed
through the guardrail engine (default-deny) rather than executed directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class ExecutePaymentTool(Tool[dict[str, Any], str]):
    """Consequential: move cash to a beneficiary (AP run / payroll disbursement).

    Moving cash is a consequential action, so it is gated by the guardrail engine
    and never invoked directly.
    """

    name = "transactional_execute_payment"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"paid:{payload.get('beneficiary')}:{payload.get('amount')}"


async def _hold_payment(
    guardrails: GuardrailEngine,
    *,
    beneficiary: str,
    amount: float,
    rationale: str,
    evidence: dict[str, Any],
    correlation_id: str | None,
) -> str | None:
    """Submit a cash movement to the gate (default-deny) and return its request id."""
    outcome = await guardrails.submit(
        ExecutePaymentTool(),
        {"beneficiary": beneficiary, "amount": amount},
        actor="transactional",
        approver_role="treasurer",
        rationale=rationale,
        evidence=evidence,
        correlation_id=correlation_id,
    )
    return outcome.request.id if outcome.request else None


class AccountsPayableSubagent(Subagent[None, dict[str, Any]]):
    """AP lane root: 3-way match invoices, then hold the payment run for approval."""

    name = "accounts-payable"

    def __init__(
        self,
        vendors: list[str],
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._vendors = vendors
        self._gateway = gateway
        self._connectors = connectors
        self._guardrails = guardrails
        self._correlation_id = correlation_id

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="match AP invoices", tier=ModelTier.HAIKU)
        matched: dict[str, float] = {}
        exceptions: list[str] = []
        for v in self._vendors:
            invoice = await _number(self._connectors, f"invoice:{v}")
            po = await _number(self._connectors, f"po:{v}")
            if invoice > 0 and invoice == po:
                matched[v] = invoice
            else:
                exceptions.append(v)

        total = sum(matched.values())
        approval_id: str | None = None
        if total > 0:
            approval_id = await _hold_payment(
                self._guardrails,
                beneficiary="ap-payment-run",
                amount=total,
                rationale=f"AP payment run of {total} across {len(matched)} vendors",
                evidence={"matched": matched},
                correlation_id=self._correlation_id,
            )
        return {
            "matched": matched,
            "exceptions": exceptions,
            "total": total,
            "approval_id": approval_id,
        }


class PayrollSubagent(Subagent[None, dict[str, Any]]):
    """Payroll lane root: total gross pay, then hold the disbursement for approval."""

    name = "payroll"

    def __init__(
        self,
        employees: list[str],
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._employees = employees
        self._gateway = gateway
        self._connectors = connectors
        self._guardrails = guardrails
        self._correlation_id = correlation_id

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run payroll", tier=ModelTier.HAIKU)
        gross = {e: await _number(self._connectors, f"payroll:{e}") for e in self._employees}
        total = sum(gross.values())
        approval_id: str | None = None
        if total > 0:
            approval_id = await _hold_payment(
                self._guardrails,
                beneficiary="payroll",
                amount=total,
                rationale=f"payroll disbursement of {total} across {len(gross)} employees",
                evidence={"gross": gross},
                correlation_id=self._correlation_id,
            )
        return {"gross": gross, "total": total, "approval_id": approval_id}


class ProcurementSubagent(Subagent[None, dict[str, Any]]):
    """Procurement lane root: track spend against budget (read-only analytics)."""

    name = "procurement"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="track procurement spend", tier=ModelTier.HAIKU)
        spend = await _number(self._connectors, "spend:total")
        budget = await _number(self._connectors, "budget:total")
        return {"spend": spend, "budget": budget, "over_budget": spend > budget}


class BillingSubagent(Subagent[None, dict[str, Any]]):
    """O2C head: generate invoices from contracts/usage (feeds accounts-receivable)."""

    name = "billing"

    def __init__(
        self, customers: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._customers = customers
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="generate invoices", tier=ModelTier.HAIKU)
        invoices = {c: await _number(self._connectors, f"contract:{c}") for c in self._customers}
        return {"invoices": invoices, "total_billed": sum(invoices.values())}


class AccountsReceivableSubagent(Subagent[None, dict[str, Any]]):
    """O2C middle: apply received cash to billed invoices, surface open items."""

    name = "accounts-receivable"

    def __init__(
        self, customers: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._customers = customers
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="apply receipts", tier=ModelTier.HAIKU)
        invoices: dict[str, float] = ctx.results["billing"]["invoices"]
        applied = {c: await _number(self._connectors, f"cash:{c}") for c in self._customers}
        open_items = {
            c: round(invoices.get(c, 0.0) - applied.get(c, 0.0), 2) for c in self._customers
        }
        return {"applied": applied, "open_items": open_items}


class CollectionsSubagent(Subagent[None, dict[str, Any]]):
    """O2C tail: dunning — flag the customers with positive open balances."""

    name = "collections"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run dunning", tier=ModelTier.HAIKU)
        open_items: dict[str, float] = ctx.results["accounts-receivable"]["open_items"]
        overdue = sorted(c for c, amount in open_items.items() if amount > 0)
        return {"overdue": overdue}


class InvoiceMatchSubagent(Subagent[None, dict[str, Any]]):
    """Parallel AP payment-run worker: 3-way match one vendor, hold its payment."""

    def __init__(
        self,
        vendor: str,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self.name = f"match:{vendor}"
        self._vendor = vendor
        self._gateway = gateway
        self._connectors = connectors
        self._guardrails = guardrails
        self._correlation_id = correlation_id

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="3-way match", tier=ModelTier.HAIKU)
        invoice = await _number(self._connectors, f"invoice:{self._vendor}")
        po = await _number(self._connectors, f"po:{self._vendor}")
        matched = invoice > 0 and invoice == po

        approval_id: str | None = None
        if matched:
            approval_id = await _hold_payment(
                self._guardrails,
                beneficiary=self._vendor,
                amount=invoice,
                rationale=f"pay vendor {self._vendor} {invoice}",
                evidence={"invoice": invoice, "po": po},
                correlation_id=self._correlation_id,
            )
        return {
            "vendor": self._vendor,
            "matched": matched,
            "amount": invoice,
            "approval_id": approval_id,
        }
