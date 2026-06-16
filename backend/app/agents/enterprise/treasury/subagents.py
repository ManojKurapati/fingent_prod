"""Treasury subagents — one stateless worker per responsibility cluster.

Numeric inputs (bank balances, AR/AP, FX exposures, debt/EBITDA, bank counts) are
pulled from connectors so the maths is deterministic and testable with fakes; the
Claude gateway is used for narrative steps. The daily-position run is read-only and
only *proposes* hedges — the **consequential** cash-movement actions (sweep / hedge
execution) are separate gated tools (:class:`ExecuteSweepTool`,
:class:`ExecuteHedgeTool`) submitted to the guardrail engine via dedicated
endpoints, never invoked directly here.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry

# Default minimum-cash buffer and leverage covenant for the placeholder models.
_DEFAULT_MIN_BUFFER = 0.0
_DEFAULT_MAX_LEVERAGE = 3.0
# Bank reconciliation tolerance.
_RECON_TOLERANCE = 0.01


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class ExecuteSweepTool(Tool[dict[str, Any], str]):
    """Consequential: move cash between accounts (sweep/pooling)."""

    name = "treasury_execute_sweep"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"swept:{payload.get('from_account')}->{payload.get('to_account')}"


class ExecuteHedgeTool(Tool[dict[str, Any], str]):
    """Consequential: execute an FX/derivative hedge (cash-movement / risk-binding)."""

    name = "treasury_execute_hedge"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"hedged:{payload.get('pair')}:{payload.get('notional')}"


class CashPositioningSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: consolidate balances and reconcile to bank statements."""

    name = "cash-positioning"

    def __init__(
        self, accounts: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._accounts = accounts
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="position cash", tier=ModelTier.HAIKU)
        by_account: dict[str, float] = {}
        breaks: list[str] = []
        for acct in self._accounts:
            book = await _number(self._connectors, f"balance:{acct}")
            bank = await _number(self._connectors, f"bank:{acct}")
            by_account[acct] = book
            if abs(book - bank) >= _RECON_TOLERANCE:
                breaks.append(acct)
        return {
            "position": round(sum(by_account.values()), 2),
            "by_account": by_account,
            "reconciled": not breaks,
            "breaks": breaks,
        }


class LiquidityForecastingSubagent(Subagent[None, dict[str, Any]]):
    """Sequential: short-term forecast off the position + working capital."""

    name = "liquidity-forecasting"

    def __init__(
        self,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        *,
        min_buffer: float = _DEFAULT_MIN_BUFFER,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._min_buffer = min_buffer

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="forecast liquidity", tier=ModelTier.HAIKU)
        position: float = ctx.results["cash-positioning"]["position"]
        ar = await _number(self._connectors, "ar")
        ap = await _number(self._connectors, "ap")
        forecast = round(position + ar - ap, 2)
        return {
            "forecast": forecast,
            "working_capital": round(ar - ap, 2),
            "min_buffer": self._min_buffer,
            "above_buffer": forecast >= self._min_buffer,
        }


class FxHedgingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel tail: identify net FX exposure and propose a hedge (no execution)."""

    name = "fx-hedging"

    def __init__(
        self, currencies: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._currencies = currencies
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="hedge exposures", tier=ModelTier.HAIKU)
        exposures = {c: await _number(self._connectors, f"fx:{c}") for c in self._currencies}
        net = round(sum(exposures.values()), 2)
        return {
            "exposures": exposures,
            "net_exposure": net,
            "proposed_hedge": net,
            "executed": False,  # the daily run only proposes; execution is gated
        }


class DebtCovenantsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel tail: leverage ratio and covenant headroom off the forecast."""

    name = "debt-covenants"

    def __init__(
        self,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        *,
        max_leverage: float = _DEFAULT_MAX_LEVERAGE,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._max_leverage = max_leverage

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="check covenants", tier=ModelTier.HAIKU)
        debt = await _number(self._connectors, "debt")
        ebitda = await _number(self._connectors, "ebitda")
        leverage = round(debt / ebitda, 2) if ebitda else 0.0
        return {
            "leverage": leverage,
            "max_leverage": self._max_leverage,
            "headroom": round(self._max_leverage - leverage, 2),
            "compliant": leverage <= self._max_leverage,
        }


class BankConnectivitySubagent(Subagent[None, dict[str, Any]]):
    """Independent standing service: report bank-portal / TMS connectivity health."""

    name = "bank-connectivity"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="check bank connectivity", tier=ModelTier.HAIKU)
        active = int(await _number(self._connectors, "active_banks"))
        return {"active_banks": active, "status": "ok" if active else "degraded"}
