"""Leadership subagents — one stateless worker per responsibility cluster.

Numeric inputs (divisional P&L, capital base) are pulled from connectors so the
maths is deterministic and testable with fakes; the Claude gateway is used for the
narrative/synthesis steps. The only **consequential** action is publishing the
board pack / investor guidance, which is routed through the guardrail engine
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


class PublishBoardPackTool(Tool[dict[str, Any], str]):
    """Consequential: publish the board pack / investor guidance externally.

    Communicating to the board / market on the org's behalf is a consequential
    action (Reg FD-style disclosure control), so it is gated by the guardrail
    engine and never invoked directly.
    """

    name = "leadership_publish_board_pack"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"published:{payload.get('period')}"


class DivisionalRollupSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: consolidate divisional P&L into a group view."""

    name = "divisional-rollup"

    def __init__(
        self, divisions: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._divisions = divisions
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="consolidate divisional P&L", tier=ModelTier.HAIKU)
        divisions = {d: await _number(self._connectors, f"pnl:{d}") for d in self._divisions}
        return {"divisions": divisions, "group_pnl": sum(divisions.values())}


class CapitalStrategySubagent(Subagent[None, dict[str, Any]]):
    """Gated behind consolidation: model capital structure + recommend allocation."""

    name = "capital-strategy"

    def __init__(
        self, target_leverage: float, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._target = target_leverage
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="model capital structure", tier=ModelTier.OPUS)
        debt = await _number(self._connectors, "capital:debt")
        equity = await _number(self._connectors, "capital:equity")
        total = debt + equity
        leverage = debt / total if total else 0.0
        recommendation = "raise_equity" if leverage > self._target else "raise_debt"
        group_pnl: float = ctx.results["divisional-rollup"]["group_pnl"]
        return {
            "leverage": leverage,
            "target": self._target,
            "headroom": self._target - leverage,
            "recommendation": recommendation,
            "group_pnl": group_pnl,
        }


class BoardInvestorReportingSubagent(Subagent[None, dict[str, Any]]):
    """Partial fan-in: assemble the board pack; publication is gated (default-deny)."""

    name = "board-investor-reporting"

    def __init__(
        self,
        period: str,
        guardrails: GuardrailEngine,
        gateway: ClaudeGateway,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._period = period
        self._guardrails = guardrails
        self._gateway = gateway
        self._correlation_id = correlation_id
        self._tool = PublishBoardPackTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="draft board narrative", tier=ModelTier.OPUS)
        consolidated = ctx.results["divisional-rollup"]
        capital = ctx.results["capital-strategy"]
        pack = {
            "period": self._period,
            "group_pnl": consolidated["group_pnl"],
            "leverage": capital["leverage"],
            "recommendation": capital["recommendation"],
        }
        outcome = await self._guardrails.submit(
            self._tool,
            {"period": self._period, "pack": pack},
            actor="leadership",
            approver_role="cfo",
            rationale=f"publish board pack for {self._period}",
            evidence=pack,
            correlation_id=self._correlation_id,
        )
        return {
            "pack": pack,
            "published": outcome.executed,
            "approval_id": outcome.request.id if outcome.request else None,
        }


class BudgetPlanSignoffSubagent(Subagent[None, dict[str, Any]]):
    """Independent lane: stage the annual budget / long-range plan for sign-off."""

    name = "budget-plan-signoff"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="stage budget signoff", tier=ModelTier.HAIKU)
        budget = await _number(self._connectors, "budget:plan")
        group_pnl: float = ctx.results["divisional-rollup"]["group_pnl"]
        return {
            "staged": True,
            "budget": budget,
            "group_pnl": group_pnl,
            "variance": group_pnl - budget,
        }


class TransformationSponsorSubagent(Subagent[None, dict[str, Any]]):
    """Independent lane: track/prioritise finance & AI-automation initiatives."""

    name = "transformation-sponsor"

    def __init__(self, connectors: ToolRegistry, gateway: ClaudeGateway) -> None:
        self._connectors = connectors
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(
            prompt="prioritise transformation initiatives", tier=ModelTier.HAIKU
        )
        count = await _number(self._connectors, "initiatives:count")
        return {"tracked": True, "initiatives": int(count)}
