"""Corp Dev & Strategy subagents — one stateless worker per responsibility.

Numeric inputs (target revenue/EBITDA, diligence flags, market sizes, consensus)
are pulled from connectors so the maths is deterministic and testable with fakes;
the Claude gateway is used for the narrative steps. The **consequential** actions —
publishing a deal recommendation to the board and publishing an external earnings
pack — are routed through the guardrail engine (default-deny).
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


class PublishDealRecommendationTool(Tool[dict[str, Any], str]):
    """Consequential: submit a deal recommendation to the board (approval gate)."""

    name = "corpdev_publish_deal"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"deal-published:{payload.get('target')}"


class PublishEarningsTool(Tool[dict[str, Any], str]):
    """Consequential: publish an external earnings pack (Reg FD-style gate)."""

    name = "corpdev_publish_earnings"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"earnings-published:{payload.get('period')}"


class PipelineSourcingSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: screen and prioritise the acquisition pipeline."""

    name = "pipeline-sourcing"

    def __init__(
        self, targets: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._targets = targets
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="screen acquisition pipeline", tier=ModelTier.HAIKU)
        scores = {t: await _number(self._connectors, f"target:revenue:{t}") for t in self._targets}
        ranked = sorted(self._targets, key=lambda t: (-scores[t], t))
        return {"scores": scores, "ranked": ranked, "top_target": ranked[0]}


class ValuationModellingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel with diligence: valuation, EV, synergies, accretion."""

    name = "valuation-modelling"

    def __init__(
        self,
        ebitda_multiple: float,
        synergy_rate: float,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
    ) -> None:
        self._multiple = ebitda_multiple
        self._synergy_rate = synergy_rate
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="build valuation model", tier=ModelTier.OPUS)
        target: str = ctx.results["pipeline-sourcing"]["top_target"]
        ebitda = await _number(self._connectors, f"target:ebitda:{target}")
        synergies = round(ebitda * self._synergy_rate, 2)
        return {
            "target": target,
            "ebitda": ebitda,
            "ev": round(ebitda * self._multiple, 2),
            "synergies": synergies,
            "accretive": synergies > 0,
        }


class DueDiligenceSubagent(Subagent[None, dict[str, Any]]):
    """Parallel with valuation: financial/commercial diligence on the target."""

    name = "due-diligence"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run due diligence", tier=ModelTier.OPUS)
        target: str = ctx.results["pipeline-sourcing"]["top_target"]
        red_flags = int(await _number(self._connectors, f"target:redflags:{target}"))
        return {"target": target, "red_flags": red_flags, "cleared": red_flags == 0}


class DealMaterialsSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: assemble the board memo; the recommendation publish is gated."""

    name = "deal-materials"

    def __init__(
        self,
        guardrails: GuardrailEngine,
        gateway: ClaudeGateway,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._guardrails = guardrails
        self._gateway = gateway
        self._correlation_id = correlation_id
        self._tool = PublishDealRecommendationTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="assemble board memo", tier=ModelTier.OPUS)
        val = ctx.results["valuation-modelling"]
        dd = ctx.results["due-diligence"]
        memo = {
            "target": val["target"],
            "ev": val["ev"],
            "accretive": val["accretive"],
            "cleared": dd["cleared"],
            "red_flags": dd["red_flags"],
        }
        recommendation = "proceed" if val["accretive"] and dd["cleared"] else "hold"
        outcome = await self._guardrails.submit(
            self._tool,
            {"target": val["target"], "recommendation": recommendation},
            actor="corpdev",
            approver_role="board",
            rationale=f"deal recommendation '{recommendation}' for {val['target']}",
            evidence=memo,
            correlation_id=self._correlation_id,
        )
        return {
            "memo": memo,
            "recommendation": recommendation,
            "approval_id": outcome.request.id if outcome.request else None,
        }


class StrategyAnalysisSubagent(Subagent[None, dict[str, Any]]):
    """Independent standing lane: market/competitor analysis and TAM."""

    name = "strategy-analysis"

    def __init__(
        self, segments: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._segments = segments
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="analyse market", tier=ModelTier.OPUS)
        sizes = {s: await _number(self._connectors, f"market:{s}") for s in self._segments}
        return {"tam": sum(sizes.values()), "by_segment": sizes}


class InvestorRelationsSubagent(Subagent[None, dict[str, Any]]):
    """Independent standing lane: earnings pack; external publish is gated."""

    name = "investor-relations"

    def __init__(
        self,
        period: str,
        guardrails: GuardrailEngine,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._period = period
        self._guardrails = guardrails
        self._gateway = gateway
        self._connectors = connectors
        self._correlation_id = correlation_id
        self._tool = PublishEarningsTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="draft earnings release", tier=ModelTier.OPUS)
        consensus = await _number(self._connectors, "ir:consensus")
        actual = await _number(self._connectors, "ir:actual")
        pack = {
            "period": self._period,
            "consensus": consensus,
            "actual": actual,
            "beat": actual >= consensus,
        }
        outcome = await self._guardrails.submit(
            self._tool,
            {"period": self._period, "pack": pack},
            actor="corpdev",
            approver_role="ir-officer",
            rationale=f"publish earnings pack for {self._period}",
            evidence=pack,
            correlation_id=self._correlation_id,
        )
        return {
            "pack": pack,
            "published": outcome.executed,
            "approval_id": outcome.request.id if outcome.request else None,
        }
