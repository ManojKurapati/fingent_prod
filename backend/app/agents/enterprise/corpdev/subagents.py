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


# Diligence workstreams run as one combined financial/legal/commercial review.
_DD_WORKSTREAMS = ("financial", "legal", "commercial", "tax", "operational")


class ValuationModellingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel with diligence: EV, synergies, and pro-forma EPS accretion/dilution.

    When acquirer financials (net income, share count, price) are connected, a
    real all-stock pro-forma EPS bridge is computed and ``accretive`` reflects
    whether combined EPS rises. With no acquirer baseline connected it falls back
    to a synergy-positive proxy so a thin deal screen still works.
    """

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
        ev = round(ebitda * self._multiple, 2)

        acquirer_ni = await _number(self._connectors, "acquirer:net_income")
        acquirer_shares = await _number(self._connectors, "acquirer:shares")
        share_price = await _number(self._connectors, "acquirer:share_price")
        target_ni = await _number(self._connectors, f"target:net_income:{target}")

        modelled = acquirer_shares > 0 and acquirer_ni != 0
        if modelled:
            acquirer_eps = acquirer_ni / acquirer_shares
            # All-stock consideration: new shares issued at the acquirer's price.
            new_shares = ev / share_price if share_price > 0 else 0.0
            proforma_ni = acquirer_ni + target_ni + synergies
            proforma_shares = acquirer_shares + new_shares
            proforma_eps = proforma_ni / proforma_shares if proforma_shares else 0.0
            accretion_pct = (proforma_eps / acquirer_eps - 1.0) if acquirer_eps else 0.0
            accretive = proforma_eps > acquirer_eps
        else:
            acquirer_eps = proforma_eps = accretion_pct = 0.0
            accretive = synergies > 0

        return {
            "target": target,
            "ebitda": ebitda,
            "ev": ev,
            "synergies": synergies,
            "acquirer_eps": round(acquirer_eps, 4),
            "proforma_eps": round(proforma_eps, 4),
            "accretion_pct": round(accretion_pct, 4),
            "modelled": modelled,
            "accretive": accretive,
        }


class DueDiligenceSubagent(Subagent[None, dict[str, Any]]):
    """Parallel with valuation: multi-workstream diligence on the target.

    Runs the standard financial/legal/commercial/tax/operational workstreams,
    each tallying red flags from the connector; a legacy aggregate red-flag key
    is folded into the financial workstream for back-compat. The target only
    clears when every workstream is clean.
    """

    name = "due-diligence"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run due diligence", tier=ModelTier.OPUS)
        target: str = ctx.results["pipeline-sourcing"]["top_target"]
        by_workstream = {
            ws: int(await _number(self._connectors, f"target:redflags:{ws}:{target}"))
            for ws in _DD_WORKSTREAMS
        }
        # Legacy aggregate red-flag key counts as a financial-diligence finding.
        by_workstream["financial"] += int(
            await _number(self._connectors, f"target:redflags:{target}")
        )
        red_flags = sum(by_workstream.values())
        open_workstreams = sorted(ws for ws, n in by_workstream.items() if n)
        return {
            "target": target,
            "by_workstream": by_workstream,
            "open_workstreams": open_workstreams,
            "red_flags": red_flags,
            "cleared": red_flags == 0,
        }


class DealMaterialsSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: assemble the board memo + a CIM; the recommendation publish is gated."""

    name = "deal-materials"

    # Sections assembled into the Confidential Information Memorandum.
    _CIM_SECTIONS = (
        "executive-summary",
        "target-overview",
        "financials",
        "valuation",
        "synergies",
        "diligence-findings",
        "recommendation",
    )

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
        # Confidential Information Memorandum assembled from the workstream outputs.
        cim = {
            "target": val["target"],
            "sections": list(self._CIM_SECTIONS),
            "financials": {"ebitda": val.get("ebitda")},
            "valuation": {
                "ev": val["ev"],
                "proforma_eps": val.get("proforma_eps"),
                "accretion_pct": val.get("accretion_pct"),
                "accretive": val["accretive"],
            },
            "synergies": val.get("synergies"),
            "diligence-findings": {
                "cleared": dd["cleared"],
                "red_flags": dd["red_flags"],
                "open_workstreams": dd.get("open_workstreams", []),
            },
            "recommendation": recommendation,
        }
        outcome = await self._guardrails.submit(
            self._tool,
            {"target": val["target"], "recommendation": recommendation},
            actor="corpdev",
            approver_role="board",
            rationale=f"deal recommendation '{recommendation}' for {val['target']}",
            evidence={"memo": memo, "cim": cim},
            correlation_id=self._correlation_id,
        )
        return {
            "memo": memo,
            "cim": cim,
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
