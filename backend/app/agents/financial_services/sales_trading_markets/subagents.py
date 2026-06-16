"""Sales & Trading / Markets subagents — one stateless worker per responsibility.

Prices, limits, and exposures are pulled from connectors so the maths is
deterministic and testable with fakes; the Claude gateway drives the
colour/narrative steps. Routing an order is the only **consequential** action: it
is denied outright unless the mandatory pre-trade risk gate clears, and otherwise
routed through the guardrail engine for trader/risk approval (default-deny).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

GATE_PASS = "PASS"
GATE_DENY = "DENY"

# Half-spread applied to the mid price when quoting a two-way market.
_HALF_SPREAD = 0.01


async def _number(connectors: ToolRegistry, key: str) -> float | None:
    """Fetch a numeric value from the connector key/value store (None if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else None


async def _text(connectors: ToolRegistry, key: str) -> str | None:
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


class RouteOrderTool(Tool[dict[str, Any], str]):
    """Consequential: route and work a client/flow order in the market."""

    name = "markets_route_order"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"routed:{payload.get('order_id')}"


class SalesCoverageSubagent(Subagent[None, dict[str, Any]]):
    """Parallel feed: cover the account, translate needs into flow."""

    name = "sales-coverage"

    def __init__(self, account: str, gateway: ClaudeGateway) -> None:
        self._account = account
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="cover accounts", tier=ModelTier.HAIKU)
        return {"account": self._account, "wallet_share": 0.1}


class PricingQuotingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel feed: quote a two-way market off the reference price."""

    name = "pricing-quoting"

    def __init__(self, instrument: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._instrument = instrument
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="quote price", tier=ModelTier.HAIKU)
        price = await _number(self._connectors, f"price:{self._instrument}") or 0.0
        return {
            "instrument": self._instrument,
            "price": price,
            "bid": round(price * (1 - _HALF_SPREAD), 4),
            "ask": round(price * (1 + _HALF_SPREAD), 4),
        }


class QuantSignalsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel feed: systematic signal for the instrument."""

    name = "quant-signals"

    def __init__(self, instrument: str, gateway: ClaudeGateway) -> None:
        self._instrument = instrument
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="scan signals", tier=ModelTier.OPUS)
        return {"instrument": self._instrument, "signal": "neutral"}


class StructuringSubagent(Subagent[None, dict[str, Any]]):
    """Parallel feed: decompose a bespoke payoff into hedgeable components."""

    name = "structuring"

    def __init__(self, instrument: str, gateway: ClaudeGateway) -> None:
        self._instrument = instrument
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="structure payoff", tier=ModelTier.HAIKU)
        return {"instrument": self._instrument, "components": ["spot", "vol"]}


class PreTradeRiskGateSubagent(Subagent[None, dict[str, Any]]):
    """MANDATORY gate: limit / inventory / suitability check before routing.

    Fail-closed — a missing limit, an over-limit notional, or an unsuitable account
    all deny the order.
    """

    name = "pre-trade-risk-gate"

    def __init__(
        self,
        account: str,
        book: str,
        quantity: float,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
    ) -> None:
        self._account = account
        self._book = book
        self._quantity = quantity
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="check pre-trade risk", tier=ModelTier.HAIKU)
        price: float = ctx.results["pricing-quoting"]["price"]
        notional = self._quantity * price

        limit = await _number(self._connectors, f"limit:{self._book}")
        exposure = await _number(self._connectors, f"exposure:{self._book}") or 0.0
        suitable = (await _text(self._connectors, f"suitable:{self._account}")) == "yes"

        within = limit is not None and (exposure + notional) <= limit
        decision = GATE_PASS if (within and suitable) else GATE_DENY
        return {
            "decision": decision,
            "book": self._book,
            "notional": notional,
            "limit": limit,
            "projected_exposure": exposure + notional,
            "suitable": suitable,
        }


class ExecutionAlgoSubagent(Subagent[None, dict[str, Any]]):
    """Gated execution: route the order only behind a cleared pre-trade risk gate.

    A deny blocks routing outright (it never reaches the approval queue); a pass
    submits the consequential routing to the guardrail engine (default-deny).
    """

    name = "execution-algo"

    def __init__(
        self, order_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._order_id = order_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = RouteOrderTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        gate = ctx.results["pre-trade-risk-gate"]
        if gate["decision"] != GATE_PASS:
            return {
                "order_id": self._order_id,
                "blocked": True,
                "routed": False,
                "approval_id": None,
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"order_id": self._order_id, "notional": gate["notional"]},
            actor="sales-trading-markets",
            approver_role="trader",
            rationale=f"route order {self._order_id} (notional {gate['notional']})",
            evidence={"book": gate["book"], "notional": gate["notional"]},
            correlation_id=self._correlation_id,
        )
        return {
            "order_id": self._order_id,
            "blocked": False,
            "routed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }


class RiskHedgingSubagent(Subagent[None, dict[str, Any]]):
    """Post-fill: mark the book and re-hedge inventory toward neutral."""

    name = "risk-hedging"

    def __init__(self, book: str, gateway: ClaudeGateway) -> None:
        self._book = book
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="rehedge book", tier=ModelTier.HAIKU)
        routed = ctx.results["execution-algo"].get("routed", False)
        return {"book": self._book, "rehedged": bool(routed)}
