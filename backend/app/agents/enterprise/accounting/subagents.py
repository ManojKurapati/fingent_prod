"""Accounting & Controllership subagents — one stateless worker per responsibility.

Numeric inputs (accruals, asset costs, inventory, contracts, GL control totals,
entity balances) are pulled from connectors so the maths is deterministic and
testable with fakes; the Claude gateway is used for narrative/judgemental steps
(notably ASC 606 technical memos). The only **consequential** action is posting
journal entries to the general ledger, which is routed through the guardrail
engine (default-deny) and never invoked directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Straight-line useful life (years) applied by the placeholder depreciation model.
_USEFUL_LIFE_YEARS = 5
# Ratable revenue periods (months) for the placeholder ASC 606 schedule.
_RATABLE_PERIODS = 12
# Reconciliation tie-out tolerance.
_RECON_TOLERANCE = 0.01


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class PostJournalEntryTool(Tool[dict[str, Any], str]):
    """Consequential: post a journal entry to the general ledger.

    A ledger write is a consequential action, so it is gated by the guardrail
    engine (Controller sign-off) and never invoked directly.
    """

    name = "accounting_post_journal_entry"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"posted:{payload.get('period')}:{payload.get('amount')}"


class CloseOrchestrationSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: open the period and gate the close calendar."""

    name = "close-orchestration"

    def __init__(self, period: str, entities: list[str], gateway: ClaudeGateway) -> None:
        self._period = period
        self._entities = entities
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="open period", tier=ModelTier.HAIKU)
        return {
            "opened": True,
            "period": self._period,
            "entities": list(self._entities),
            "note": resp.text,
        }


class JournalEntriesSubagent(Subagent[None, dict[str, Any]]):
    """Parallel sub-ledger: prepare routine JEs and gate the GL post for approval."""

    name = "journal-entries"

    def __init__(
        self,
        entities: list[str],
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._entities = entities
        self._gateway = gateway
        self._connectors = connectors
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = PostJournalEntryTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="prepare journal entries", tier=ModelTier.HAIKU)
        accruals = {e: await _number(self._connectors, f"accrual:{e}") for e in self._entities}
        total = round(sum(accruals.values()), 2)
        # Consequential: do NOT post directly — submit for Controller approval.
        period = ctx.results.get("close-orchestration", {}).get("period")
        outcome = await self._guardrails.submit(
            self._tool,
            {"period": period, "amount": total},
            actor="accounting",
            approver_role="controller",
            rationale=f"post period-close journal entries totalling {total}",
            evidence={"accruals": accruals, "total": total},
            correlation_id=self._correlation_id,
        )
        return {
            "accruals": accruals,
            "total": total,
            "posted": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }


class FixedAssetsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel sub-ledger: straight-line depreciation off the asset register."""

    name = "fixed-assets"

    def __init__(
        self, entities: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._entities = entities
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="compute depreciation", tier=ModelTier.HAIKU)
        depreciation = {
            e: round(await _number(self._connectors, f"asset_cost:{e}") / _USEFUL_LIFE_YEARS, 2)
            for e in self._entities
        }
        return {
            "depreciation": depreciation,
            "total_depreciation": round(sum(depreciation.values()), 2),
        }


class CostInventorySubagent(Subagent[None, dict[str, Any]]):
    """Parallel sub-ledger: inventory valuation and standard-cost variance."""

    name = "cost-inventory"

    def __init__(
        self, entities: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._entities = entities
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="value inventory", tier=ModelTier.HAIKU)
        variance: dict[str, float] = {}
        for e in self._entities:
            actual = await _number(self._connectors, f"inventory:{e}")
            standard = await _number(self._connectors, f"std_cost:{e}")
            variance[e] = round(actual - standard, 2)
        return {"variance": variance, "total_variance": round(sum(variance.values()), 2)}


class TechnicalAccountingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel sub-ledger: ASC 606 / IFRS 15 ratable revenue for new contracts."""

    name = "technical-accounting"

    def __init__(
        self, entities: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._entities = entities
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="asc606 review", tier=ModelTier.OPUS)
        schedule = {
            e: round(await _number(self._connectors, f"contract:{e}") / _RATABLE_PERIODS, 2)
            for e in self._entities
        }
        return {"revenue_schedule": schedule, "memo": resp.text}


class ReconciliationsSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: tie the posted sub-ledgers to the GL control total; flag exceptions."""

    name = "reconciliations"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="reconcile subledgers", tier=ModelTier.HAIKU)
        subledger_total = round(
            ctx.results["journal-entries"]["total"]
            + ctx.results["fixed-assets"]["total_depreciation"]
            + ctx.results["cost-inventory"]["total_variance"],
            2,
        )
        gl_control = await _number(self._connectors, "gl_control")
        difference = round(subledger_total - gl_control, 2)
        tied = abs(difference) < _RECON_TOLERANCE
        return {
            "subledger_total": subledger_total,
            "gl_control": gl_control,
            "difference": difference,
            "tied": tied,
            "exceptions": [] if tied else ["gl_control"],
        }


class ConsolidationsSubagent(Subagent[None, dict[str, Any]]):
    """Sequenced last: multi-entity consolidation, FX translation, IC elimination."""

    name = "consolidations"

    def __init__(
        self, entities: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._entities = entities
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="consolidate entities", tier=ModelTier.HAIKU)
        by_entity: dict[str, float] = {}
        eliminations: dict[str, float] = {}
        for e in self._entities:
            balance = await _number(self._connectors, f"entity_balance:{e}")
            rate = await _number(self._connectors, f"fx_rate:{e}") or 1.0
            ic = await _number(self._connectors, f"ic:{e}")
            eliminations[e] = ic
            by_entity[e] = round(balance * rate - ic, 2)
        return {
            "by_entity": by_entity,
            "eliminations": eliminations,
            "group_total": round(sum(by_entity.values()), 2),
        }
