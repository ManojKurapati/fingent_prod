"""Asset & Investment Management subagents — one worker per responsibility cluster.

Target weights, limits, and liquidity are pulled from connectors so the maths is
deterministic and testable with fakes; the Claude gateway drives the
research/narrative steps. Placing orders is the only **consequential** action: it
is denied outright unless the mandatory mandate/risk gate clears, and otherwise
routed through the guardrail engine for PM approval (default-deny).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

GATE_PASS = "PASS"
GATE_DENY = "DENY"


async def _number(connectors: ToolRegistry, key: str) -> float | None:
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else None


async def _text(connectors: ToolRegistry, key: str) -> str | None:
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


class PlaceOrdersTool(Tool[dict[str, Any], str]):
    """Consequential: place the rebalance trade list with the dealing desk."""

    name = "aim_place_orders"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"placed:{payload.get('portfolio_id')}"


class MacroStrategySubagent(Subagent[None, dict[str, Any]]):
    """Sequential spine head: produce the house macro view."""

    name = "macro-strategy"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="house macro view", tier=ModelTier.OPUS)
        return {"house_view": resp.text or "neutral"}


class AssetAllocationSubagent(Subagent[None, dict[str, Any]]):
    """Sequential spine tail: translate the macro view into target tilts."""

    name = "asset-allocation"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="set allocation tilts", tier=ModelTier.HAIKU)
        house_view = ctx.results["macro-strategy"]["house_view"]
        return {"house_view": house_view, "tilts": {"equity": 0.6, "rates": 0.4}}


class BuysideResearchSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: one independent name recommendation."""

    def __init__(self, name: str, gateway: ClaudeGateway) -> None:
        self.name = f"research:{name}"
        self._covered = name
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt=f"research {self._covered}", tier=ModelTier.HAIKU)
        return {"name": self._covered, "recommendation": "buy", "conviction": 0.7}


class PortfolioConstructionSubagent(Subagent[None, dict[str, Any]]):
    """Join: build the target portfolio from the allocation + research streams."""

    name = "portfolio-construction"

    def __init__(
        self, portfolio_id: str, names: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._portfolio_id = portfolio_id
        self._names = names
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="construct portfolio", tier=ModelTier.HAIKU)
        targets = {n: (await _number(self._connectors, f"target:{n}") or 0.0) for n in self._names}
        return {
            "portfolio_id": self._portfolio_id,
            "targets": targets,
            "target_notional": sum(targets.values()),
        }


class MandateRiskGateSubagent(Subagent[None, dict[str, Any]]):
    """MANDATORY gate: limit / liquidity / suitability check before execution.

    Fail-closed — a missing limit, an over-limit target, or stressed liquidity all
    deny the rebalance.
    """

    name = "mandate-risk-gate"

    def __init__(self, portfolio_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._portfolio_id = portfolio_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="check mandate and risk", tier=ModelTier.HAIKU)
        target_notional: float = ctx.results["portfolio-construction"]["target_notional"]
        limit = await _number(self._connectors, f"limit:{self._portfolio_id}")
        liquid = (await _text(self._connectors, f"liquidity:{self._portfolio_id}")) == "ok"

        within = limit is not None and target_notional <= limit
        decision = GATE_PASS if (within and liquid) else GATE_DENY
        return {
            "decision": decision,
            "portfolio_id": self._portfolio_id,
            "target_notional": target_notional,
            "limit": limit,
            "liquid": liquid,
        }


class BuysideExecutionSubagent(Subagent[None, dict[str, Any]]):
    """Gated execution: place orders only behind a cleared mandate/risk gate.

    A deny blocks placement outright (it never reaches the approval queue); a pass
    submits the consequential placement to the guardrail engine (default-deny).
    """

    name = "buyside-execution"

    def __init__(
        self, portfolio_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._portfolio_id = portfolio_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = PlaceOrdersTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        gate = ctx.results["mandate-risk-gate"]
        if gate["decision"] != GATE_PASS:
            return {
                "portfolio_id": self._portfolio_id,
                "blocked": True,
                "placed": False,
                "approval_id": None,
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"portfolio_id": self._portfolio_id, "target_notional": gate["target_notional"]},
            actor="asset-investment-management",
            approver_role="portfolio-manager",
            rationale=f"place rebalance orders for {self._portfolio_id}",
            evidence={"target_notional": gate["target_notional"], "limit": gate.get("limit")},
            correlation_id=self._correlation_id,
        )
        return {
            "portfolio_id": self._portfolio_id,
            "blocked": False,
            "placed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }
