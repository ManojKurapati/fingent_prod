"""Risk Management subagents — one stateless worker per risk type, plus the
synchronous gates this agent publishes to the rest of the firm.

Each measure reads its metric + limit from connectors (deterministic, fakeable).
``erm-aggregation`` is the join: it consolidates breaches and, when appetite is
exceeded, routes a CRO limit-override through the guardrail engine (default-deny).
The ``pre_trade_gate`` / ``limit_check_gate`` helpers are the mandatory,
fail-closed checks other agents call before committing capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Names of the four risk-type measures + the assurance check.
_BREACH_MEASURES = ("market-risk", "credit-risk", "operational-risk", "liquidity-risk")


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Outcome of a synchronous risk gate."""

    decision: str  # "PASS" | "DENY"
    reason: str
    token: str | None
    headroom: float


async def pre_trade_gate(connectors: ToolRegistry, book: str, notional: float) -> GateDecision:
    """Mandatory pre-trade check: would the trade keep the book within its limit?

    Fail-closed: an absent limit reads as 0.0 so any positive proposed exposure is
    denied. Returns a token only on PASS — the consequential endpoint requires it.
    """
    exposure = await _number(connectors, f"exposure:{book}")
    limit = await _number(connectors, f"limit:{book}")
    proposed = round(exposure + notional, 2)
    if limit > 0.0 and proposed <= limit:
        return GateDecision(
            decision="PASS",
            reason=f"proposed {proposed} within limit {limit}",
            token=f"risk-gate:pre-trade:{book}:{proposed}",
            headroom=round(limit - proposed, 2),
        )
    return GateDecision(
        decision="DENY",
        reason=f"proposed {proposed} exceeds limit {limit}",
        token=None,
        headroom=round(limit - proposed, 2),
    )


async def limit_check_gate(connectors: ToolRegistry, book: str) -> GateDecision:
    """Mandatory limit check on current exposure (fail-closed on absent limit)."""
    exposure = await _number(connectors, f"exposure:{book}")
    limit = await _number(connectors, f"limit:{book}")
    if limit > 0.0 and exposure <= limit:
        return GateDecision(
            decision="PASS",
            reason=f"exposure {exposure} within limit {limit}",
            token=f"risk-gate:limit-check:{book}",
            headroom=round(limit - exposure, 2),
        )
    return GateDecision(
        decision="DENY",
        reason=f"exposure {exposure} exceeds limit {limit}",
        token=None,
        headroom=round(limit - exposure, 2),
    )


class RequestLimitOverrideTool(Tool[dict[str, Any], str]):
    """Consequential: escalate a limit breach to the CRO for an override decision."""

    name = "risk_request_limit_override"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"escalated:{payload.get('breaches')}"


class MarketRiskSubagent(Subagent[None, dict[str, Any]]):
    """Measure: VaR vs limit on the trading/banking book."""

    name = "market-risk"

    def __init__(self, book: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._book = book
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="market risk", tier=ModelTier.HAIKU)
        var = await _number(self._connectors, f"var:{self._book}")
        limit = await _number(self._connectors, f"varlimit:{self._book}")
        return {"var": var, "limit": limit, "breach": var > limit}


class CreditRiskSubagent(Subagent[None, dict[str, Any]]):
    """Measure: expected credit loss vs provision limit."""

    name = "credit-risk"

    def __init__(self, book: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._book = book
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="credit risk", tier=ModelTier.HAIKU)
        ecl = await _number(self._connectors, f"ecl:{self._book}")
        limit = await _number(self._connectors, f"ecllimit:{self._book}")
        return {"ecl": ecl, "limit": limit, "breach": ecl > limit}


class OperationalRiskSubagent(Subagent[None, dict[str, Any]]):
    """Measure: operational loss vs appetite."""

    name = "operational-risk"

    def __init__(self, book: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._book = book
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="operational risk", tier=ModelTier.HAIKU)
        loss = await _number(self._connectors, f"oploss:{self._book}")
        limit = await _number(self._connectors, f"oplosslimit:{self._book}")
        return {"oploss": loss, "limit": limit, "breach": loss > limit}


class LiquidityRiskSubagent(Subagent[None, dict[str, Any]]):
    """Measure: LCR vs regulatory floor (breach when below the floor)."""

    name = "liquidity-risk"

    def __init__(self, book: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._book = book
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="liquidity risk", tier=ModelTier.HAIKU)
        lcr = await _number(self._connectors, f"lcr:{self._book}")
        floor = await _number(self._connectors, f"lcrmin:{self._book}")
        return {"lcr": lcr, "floor": floor, "breach": lcr < floor}


class ModelValidationSubagent(Subagent[None, dict[str, Any]]):
    """Independent assurance: validate models against a drift tolerance."""

    name = "model-validation"

    def __init__(self, book: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._book = book
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="model validation", tier=ModelTier.HAIKU)
        drift = await _number(self._connectors, f"modeldrift:{self._book}")
        tolerance = await _number(self._connectors, f"driftlimit:{self._book}")
        return {"drift": drift, "tolerance": tolerance, "validated": drift <= tolerance}


class ErmAggregationSubagent(Subagent[None, dict[str, Any]]):
    """Barrier/join: consolidate measures; escalate breaches to the CRO (gated)."""

    name = "erm-aggregation"

    def __init__(self, guardrails: GuardrailEngine, *, correlation_id: str | None = None) -> None:
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = RequestLimitOverrideTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        breaches = sorted(
            m for m in _BREACH_MEASURES if ctx.results.get(m, {}).get("breach") is True
        )
        if ctx.results.get("model-validation", {}).get("validated") is False:
            breaches.append("model-validation")
        within_appetite = not breaches

        approval_id: str | None = None
        if breaches:
            outcome = await self._guardrails.submit(
                self._tool,
                {"breaches": breaches},
                actor="risk",
                approver_role="cro",
                rationale=f"limit breach escalation: {breaches}",
                evidence={"breaches": breaches},
                correlation_id=self._correlation_id,
            )
            approval_id = outcome.request.id if outcome.request else None

        return {
            "breaches": breaches,
            "within_appetite": within_appetite,
            "escalated": bool(breaches),
            "approval_id": approval_id,
        }
