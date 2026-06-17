"""Tax subagents — one stateless worker per responsibility cluster.

Per-jurisdiction tax computations are deterministic off connector inputs; the
Claude gateway is used for the narrative/judgement step. The provision fan-in
assembles current + deferred tax into an ETR. Filing a return externally is the
only **consequential** action and is routed through the guardrail engine
(default-deny) rather than executed directly.
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


class FileReturnTool(Tool[dict[str, Any], str]):
    """Consequential: submit a tax return to a revenue authority.

    Filing externally is a consequential action, so it is gated by the guardrail
    engine and never invoked directly.
    """

    name = "tax_file_return"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"filed:{payload.get('return_id')}:{payload.get('jurisdiction')}"


class DirectTaxComplianceSubagent(Subagent[None, dict[str, Any]]):
    """Parallel stream: corporate income-tax computation per jurisdiction."""

    name = "direct-tax-compliance"

    def __init__(
        self, jurisdictions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._jurisdictions = jurisdictions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="compute direct tax", tier=ModelTier.HAIKU)
        current_tax: dict[str, float] = {}
        total_income = 0.0
        for j in self._jurisdictions:
            income = await _number(self._connectors, f"income:{j}")
            rate = await _number(self._connectors, f"rate:{j}")
            current_tax[j] = round(income * rate, 2)
            total_income += income
        # A filing-ready corporate-income return is prepared per jurisdiction.
        filings = {
            j: {"form": "corporate-income", "tax_due": current_tax[j], "status": "ready"}
            for j in self._jurisdictions
        }
        return {
            "current_tax": current_tax,
            "total_current": sum(current_tax.values()),
            "total_income": total_income,
            "filings": filings,
        }


class IndirectTaxSubagent(Subagent[None, dict[str, Any]]):
    """Parallel stream: VAT/GST output netted against recoverable input credits."""

    name = "indirect-tax"

    def __init__(
        self, jurisdictions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._jurisdictions = jurisdictions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="compute indirect tax", tier=ModelTier.HAIKU)
        net_vat: dict[str, float] = {}
        for j in self._jurisdictions:
            output = await _number(self._connectors, f"vat_out:{j}")
            recoverable = await _number(self._connectors, f"vat_in:{j}")
            net_vat[j] = round(output - recoverable, 2)
        filings = {
            j: {"form": "vat-gst", "net_due": net_vat[j], "status": "ready"}
            for j in self._jurisdictions
        }
        return {"net_vat": net_vat, "total": sum(net_vat.values()), "filings": filings}


class TransferPricingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel stream: intercompany pricing adjustments per jurisdiction."""

    name = "transfer-pricing"

    def __init__(
        self, jurisdictions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._jurisdictions = jurisdictions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="document transfer pricing", tier=ModelTier.HAIKU)
        adjustments = {
            j: await _number(self._connectors, f"intercompany:{j}") for j in self._jurisdictions
        }
        return {"adjustments": adjustments, "total": sum(adjustments.values())}


class InternationalTaxSubagent(Subagent[None, dict[str, Any]]):
    """Parallel stream: cross-border withholding / foreign tax credits."""

    name = "international-tax"

    def __init__(
        self, jurisdictions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._jurisdictions = jurisdictions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="assess international tax", tier=ModelTier.HAIKU)
        foreign_credits = {
            j: await _number(self._connectors, f"foreign_tax:{j}") for j in self._jurisdictions
        }
        filings = {
            j: {"form": "withholding-ftc", "foreign_credit": foreign_credits[j], "status": "ready"}
            for j in self._jurisdictions
        }
        return {
            "foreign_credits": foreign_credits,
            "total": sum(foreign_credits.values()),
            "filings": filings,
        }


async def _build_defence_file(connectors: ToolRegistry | None, jurisdiction: str) -> dict[str, Any]:
    """Assemble the audit-defence file for one jurisdiction (positions + open disputes)."""
    open_disputes = 0
    if connectors is not None:
        open_disputes = int(await _number(connectors, f"dispute:{jurisdiction}"))
    return {
        "jurisdiction": jurisdiction,
        "open_disputes": open_disputes,
        "positions_documented": True,
        "ready": True,
    }


class AuditDefenceSubagent(Subagent[None, dict[str, Any]]):
    """Standing parallel stream: assemble audit-defence files per jurisdiction."""

    name = "audit-defence"

    def __init__(
        self, jurisdictions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._jurisdictions = jurisdictions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="monitor disputes", tier=ModelTier.HAIKU)
        open_disputes: list[str] = []
        defence_files: dict[str, Any] = {}
        for j in self._jurisdictions:
            defence_files[j] = await _build_defence_file(self._connectors, j)
            if defence_files[j]["open_disputes"] > 0:
                open_disputes.append(j)
        return {
            "open_disputes": sorted(open_disputes),
            "defence_files": defence_files,
            "ready": True,
        }


class TaxProvisionSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: assemble current + deferred tax into the ETR + disclosures."""

    name = "tax-provision"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="assemble provision and ETR", tier=ModelTier.OPUS)
        direct = ctx.results["direct-tax-compliance"]
        current: float = direct["total_current"]
        total_income: float = direct["total_income"]
        tp_total: float = ctx.results["transfer-pricing"]["total"]
        intl_total: float = ctx.results["international-tax"]["total"]
        deferred = round(tp_total + intl_total, 2)
        total_tax = round(current + deferred, 2)
        etr = total_tax / total_income if total_income else 0.0
        return {
            "current": current,
            "deferred": deferred,
            "total_tax": total_tax,
            "etr": etr,
            "disclosures": {"effective_tax_rate": etr, "total_tax": total_tax},
        }


class TaxFilingSubagent(Subagent[None, dict[str, Any]]):
    """Sequential filing path: hold the external submission for approval."""

    name = "file-return"

    def __init__(
        self,
        return_id: str,
        jurisdiction: str,
        gateway: ClaudeGateway,
        guardrails: GuardrailEngine,
        connectors: ToolRegistry | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._return_id = return_id
        self._jurisdiction = jurisdiction
        self._gateway = gateway
        self._guardrails = guardrails
        self._connectors = connectors
        self._correlation_id = correlation_id
        self._tool = FileReturnTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="prepare filing", tier=ModelTier.HAIKU)
        # Assemble the audit-defence file for the jurisdiction *before* filing, so the
        # approver reviews the defence position alongside the submission.
        defence_file = await _build_defence_file(self._connectors, self._jurisdiction)
        outcome = await self._guardrails.submit(
            self._tool,
            {"return_id": self._return_id, "jurisdiction": self._jurisdiction},
            actor="tax",
            approver_role="head-of-tax",
            rationale=f"file return {self._return_id} in {self._jurisdiction}",
            evidence={
                "return_id": self._return_id,
                "jurisdiction": self._jurisdiction,
                "defence_file": defence_file,
            },
            correlation_id=self._correlation_id,
        )
        return {
            "return_id": self._return_id,
            "jurisdiction": self._jurisdiction,
            "defence_file": defence_file,
            "filed": outcome.executed,
            "approval_id": outcome.request.id if outcome.request else None,
        }
