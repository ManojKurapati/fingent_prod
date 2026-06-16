"""Operations subagents — one stateless worker per responsibility cluster.

Numeric reconciliation inputs are pulled from connectors so the maths is
deterministic and testable with fakes; the Claude gateway is used for the
narrative/validation steps. The only **consequential** action is instructing
settlement (it moves cash/securities), which is refused for an unconfirmed trade
and otherwise routed through the guardrail engine (default-deny).
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


class SettlementInstructionTool(Tool[dict[str, Any], str]):
    """Consequential: instruct cash/securities settlement at the custodian/CSD.

    Moving assets is a consequential action, so it is gated by the guardrail
    engine and never invoked directly.
    """

    name = "ops_instruct_settlement"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"settled:{payload.get('trade_id')}"


class TradeSupportSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: validate/enrich the capture and confirm with the counterparty."""

    name = "trade-support"

    def __init__(self, trade_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._trade_id = trade_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="confirm trade", tier=ModelTier.HAIKU)
        affirmed = await self._connectors.get("kv_read").invoke(f"trade:{self._trade_id}:affirmed")
        return {
            "trade_id": self._trade_id,
            "confirmed": affirmed == "yes",
            "note": resp.text,
        }


class SettlementsSubagent(Subagent[None, dict[str, Any]]):
    """Sequential gate: instruct settlement only for a confirmed trade (consequential)."""

    name = "settlements"

    def __init__(
        self,
        trade_id: str,
        amount: float,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._trade_id = trade_id
        self._amount = amount
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = SettlementInstructionTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        confirmed: bool = ctx.results["trade-support"]["confirmed"]
        if not confirmed:
            # You cannot settle an unconfirmed trade — refuse, do not even submit.
            return {
                "blocked": True,
                "requested": False,
                "executed": False,
                "approval_id": None,
                "reason": "trade not confirmed",
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"trade_id": self._trade_id, "amount": self._amount},
            actor="ops",
            approver_role="ops-controller",
            rationale=f"instruct settlement of {self._amount} for {self._trade_id}",
            evidence={"trade_id": self._trade_id, "amount": self._amount},
            correlation_id=self._correlation_id,
        )
        return {
            "blocked": False,
            "requested": True,
            "executed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }


class ReconciliationsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel surface: cash/position recon between internal and external books."""

    name = "reconciliations"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="reconcile books", tier=ModelTier.HAIKU)
        internal = await _number(self._connectors, "recon:internal")
        external = await _number(self._connectors, "recon:external")
        break_amount = round(internal - external, 2)
        return {
            "internal": internal,
            "external": external,
            "break_amount": break_amount,
            "has_break": break_amount != 0.0,
        }


class FundAccountingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel surface: strike NAV from assets/liabilities/shares."""

    name = "fund-accounting"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="compute nav", tier=ModelTier.HAIKU)
        assets = await _number(self._connectors, "nav:assets")
        liabilities = await _number(self._connectors, "nav:liabilities")
        shares = await _number(self._connectors, "nav:shares")
        nav = round((assets - liabilities) / shares, 4) if shares else 0.0
        return {"assets": assets, "liabilities": liabilities, "shares": shares, "nav": nav}


class CustodyOpsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel surface: reconcile holdings against the sub-custodian's records."""

    name = "custody-ops"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="reconcile custody", tier=ModelTier.HAIKU)
        holdings = await _number(self._connectors, "custody:holdings")
        custodian = await _number(self._connectors, "custody:custodian")
        return {"holdings": holdings, "custodian": custodian, "reconciled": holdings == custodian}


class CollateralMgmtSubagent(Subagent[None, dict[str, Any]]):
    """Parallel surface: size the margin call from exposure vs posted collateral."""

    name = "collateral-mgmt"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="manage collateral", tier=ModelTier.HAIKU)
        exposure = await _number(self._connectors, "collateral:exposure")
        posted = await _number(self._connectors, "collateral:posted")
        return {
            "exposure": exposure,
            "posted": posted,
            "margin_call": round(max(exposure - posted, 0.0), 2),
        }
