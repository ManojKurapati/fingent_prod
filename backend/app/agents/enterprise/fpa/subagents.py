"""FP&A subagents — one stateless worker per responsibility cluster.

Numeric inputs (actuals, plan) are pulled from connectors so the maths is
deterministic and testable with fakes; the Claude gateway is used for the
narrative/validation steps. The only **consequential** action is requesting
variance commentary from a cost-centre owner, which is routed through the
guardrail engine (default-deny) rather than executed directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Driver applied by the placeholder forecast model (5% growth on plan).
_FORECAST_GROWTH = 0.05


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class RequestCommentaryTool(Tool[dict[str, Any], str]):
    """Consequential: ping a cost-centre owner to explain a variance breach.

    Communicating externally on the org's behalf is a consequential action, so it
    is gated by the guardrail engine and never invoked directly.
    """

    name = "fpa_request_commentary"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"requested:{payload.get('cost_centre')}"


class DataIntakeSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: validate inputs and load actuals before any modelling."""

    name = "data-intake"

    def __init__(
        self,
        period: str,
        cost_centres: list[str],
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
    ) -> None:
        self._period = period
        self._cost_centres = cost_centres
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="validate FP&A intake", tier=ModelTier.HAIKU)
        actuals = {cc: await _number(self._connectors, f"actual:{cc}") for cc in self._cost_centres}
        return {
            "validated": True,
            "period": self._period,
            "cost_centres": list(self._cost_centres),
            "actuals": actuals,
            "note": resp.text,
        }


class BudgetConsolidationSubagent(Subagent[None, dict[str, Any]]):
    """Consolidate departmental budget submissions into one plan."""

    name = "budget-consolidation"

    def __init__(
        self, cost_centres: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._cost_centres = cost_centres
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="consolidate budget", tier=ModelTier.HAIKU)
        plan = {cc: await _number(self._connectors, f"plan:{cc}") for cc in self._cost_centres}
        return {"plan": plan, "total_plan": sum(plan.values())}


class ForecastEngineSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: driver-based forecast off the consolidated plan."""

    name = "forecast-engine"

    def __init__(self, cost_centres: list[str], gateway: ClaudeGateway) -> None:
        self._cost_centres = cost_centres
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run forecast", tier=ModelTier.HAIKU)
        plan: dict[str, float] = ctx.results["budget-consolidation"]["plan"]
        forecast = {cc: round(plan.get(cc, 0.0) * (1 + _FORECAST_GROWTH), 2) for cc in plan}
        return {"forecast": forecast}


class RevenueAnalyticsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: revenue forecasting / ARR off consolidated totals."""

    name = "revenue-analytics"

    def __init__(self, cost_centres: list[str], gateway: ClaudeGateway) -> None:
        self._cost_centres = cost_centres
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="analyze revenue", tier=ModelTier.HAIKU)
        total_plan: float = ctx.results["budget-consolidation"]["total_plan"]
        return {"arr": total_plan, "by_segment": {"core": total_plan}}


class ScenarioModellingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out (and standalone): scenario/sensitivity off actuals base."""

    name = "scenario-modelling"

    def __init__(self, period: str, drivers: dict[str, float], gateway: ClaudeGateway) -> None:
        self._period = period
        self._drivers = drivers
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="model scenario", tier=ModelTier.OPUS)
        actuals: dict[str, float] = ctx.results["data-intake"]["actuals"]
        base = sum(actuals.values())
        adjusted = base * (1 + sum(self._drivers.values()))
        return {"base": base, "adjusted": adjusted, "drivers": dict(self._drivers)}


class VarianceSubagent(Subagent[None, dict[str, Any]]):
    """Per-cost-centre variance; a breach requests commentary via the gate."""

    def __init__(
        self,
        cost_centre: str,
        guardrails: GuardrailEngine,
        *,
        threshold: float = 0.1,
        correlation_id: str | None = None,
    ) -> None:
        self.name = f"variance:{cost_centre}"
        self._cost_centre = cost_centre
        self._guardrails = guardrails
        self._threshold = threshold
        self._correlation_id = correlation_id
        self._tool = RequestCommentaryTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        cc = self._cost_centre
        actual: float = ctx.results["data-intake"]["actuals"].get(cc, 0.0)
        plan: float = ctx.results["budget-consolidation"]["plan"].get(cc, 0.0)
        variance = (actual - plan) / plan if plan else 0.0
        breach = abs(variance) >= self._threshold

        approval_id: str | None = None
        if breach:
            outcome = await self._guardrails.submit(
                self._tool,
                {"cost_centre": cc, "variance": variance},
                actor="fpa",
                approver_role="fpa-manager",
                rationale=f"variance {variance:.1%} on {cc} exceeds {self._threshold:.0%}",
                evidence={"actual": actual, "plan": plan, "variance": variance},
                correlation_id=self._correlation_id,
            )
            approval_id = outcome.request.id if outcome.request else None

        return {
            "cost_centre": cc,
            "actual": actual,
            "plan": plan,
            "variance": variance,
            "breach": breach,
            "commentary_requested": breach,
            "approval_id": approval_id,
        }


class ReportingPacksSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: assemble the consolidated planning pack from every fan-out output."""

    name = "reporting-packs"

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        variances = {k: v for k, v in ctx.results.items() if k.startswith("variance:")}
        breaches = sorted(v["cost_centre"] for v in variances.values() if v.get("breach"))
        sections = [
            name
            for name in ("forecast-engine", "revenue-analytics", "scenario-modelling")
            if name in ctx.results
        ]
        pack = {
            "cost_centres": len(variances),
            "sections": sections,
            "forecast": ctx.results.get("forecast-engine", {}).get("forecast"),
            "arr": ctx.results.get("revenue-analytics", {}).get("arr"),
            "scenario": ctx.results.get("scenario-modelling"),
        }
        return {"pack": pack, "sections": len(sections), "breaches": breaches}
