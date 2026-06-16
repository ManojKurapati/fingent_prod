"""Private Markets subagents — one stateless worker per responsibility cluster.

Numeric deal metrics (leverage, MOIC, IRR, track record, covenant headroom) are
pulled from connectors so the underwriting maths is deterministic and testable; the
Claude gateway is used only for narrative steps. The single **consequential** action
— committing capital at close — is routed through the guardrail engine (default-deny)
and is never executed directly: it is the mandatory Investment Committee gate.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Asset-class underwriting thresholds (invest iff the metric clears the bar).
_MAX_LEVERAGE = 6.0  # direct lending: debt / EBITDA ceiling
_MIN_MOIC = 2.0  # PE/VC: minimum modelled money multiple
_MIN_IRR = 0.12  # real assets: minimum levered IRR
_MIN_TRACK = 0.7  # fund-of-funds: minimum GP track-record score


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class CommitCapitalTool(Tool[dict[str, Any], str]):
    """Consequential: commit fund capital to close a deal.

    Committing capital is a consequential action, so it is gated by the guardrail
    engine (the Investment Committee approval gate) and never invoked directly.
    """

    name = "pm_commit_capital"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"committed:{payload.get('deal_id')}"


class OriginationPipelineSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: screen an inbound/sourced deal against the thesis."""

    name = "origination-pipeline"

    def __init__(self, deal_id: str, asset_class: str, gateway: ClaudeGateway) -> None:
        self._deal_id = deal_id
        self._asset_class = asset_class
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="screen pipeline", tier=ModelTier.HAIKU)
        return {
            "qualified": True,
            "deal_id": self._deal_id,
            "asset_class": self._asset_class,
            "note": resp.text,
        }


class DiligenceSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: one independent diligence workstream on the deal."""

    def __init__(
        self, workstream: str, deal_id: str, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self.name = f"diligence:{workstream}"
        self._workstream = workstream
        self._deal_id = deal_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(
            prompt=f"diligence {self._workstream}", tier=ModelTier.HAIKU
        )
        return {"workstream": self._workstream, "ok": True, "findings": resp.text}


class _UnderwritingSubagent(Subagent[None, dict[str, Any]]):
    """Shared base for asset-class underwriting: read a metric, decide invest/pass."""

    metric_key: str
    tier = ModelTier.OPUS

    def __init__(self, deal_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._deal_id = deal_id
        self._gateway = gateway
        self._connectors = connectors

    def _decide(self, metric: float) -> bool:
        raise NotImplementedError

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="underwrite deal", tier=self.tier)
        metric = await _number(self._connectors, f"{self.metric_key}:{self._deal_id}")
        invest = self._decide(metric)
        return {
            "deal_id": self._deal_id,
            "metric": metric,
            "recommendation": "invest" if invest else "pass",
            "ic_memo": {"deal_id": self._deal_id, "metric": metric, "invest": invest},
        }


class PeVcUnderwritingSubagent(_UnderwritingSubagent):
    """Buyout/growth/venture underwriting: invest on a strong modelled MOIC."""

    name = "pe-vc-underwriting"
    metric_key = "pm:moic"

    def _decide(self, metric: float) -> bool:
        return metric >= _MIN_MOIC


class CreditUnderwritingSubagent(_UnderwritingSubagent):
    """Direct-lending underwriting: invest when leverage is within appetite."""

    name = "credit-underwriting"
    metric_key = "pm:leverage"

    def _decide(self, metric: float) -> bool:
        return 0.0 < metric <= _MAX_LEVERAGE


class RealAssetUnderwritingSubagent(_UnderwritingSubagent):
    """Real-estate / infrastructure underwriting: invest on a sufficient IRR."""

    name = "real-asset-underwriting"
    metric_key = "pm:irr"

    def _decide(self, metric: float) -> bool:
        return metric >= _MIN_IRR


class FundOfFundsSubagent(_UnderwritingSubagent):
    """GP selection: invest when the manager's track-record score clears the bar."""

    name = "fund-of-funds"
    metric_key = "pm:track"

    def _decide(self, metric: float) -> bool:
        return metric >= _MIN_TRACK


class IcCommitmentSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in close: route the consequential capital commitment to the IC gate.

    No capital is committed before the human Investment Committee signs; a deal the
    underwriting recommends to ``pass`` proposes no commitment at all.
    """

    name = "ic-commitment"

    def __init__(
        self, deal_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._deal_id = deal_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = CommitCapitalTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        underwriting: dict[str, Any] = next(
            (
                v
                for k, v in ctx.results.items()
                if k.endswith("underwriting") or k == "fund-of-funds"
            ),
            {},
        )
        recommendation = underwriting.get("recommendation", "pass")
        if recommendation != "invest":
            return {"committed": False, "approval_id": None, "recommendation": recommendation}

        outcome = await self._guardrails.submit(
            self._tool,
            {"deal_id": self._deal_id},
            actor="private-markets",
            approver_role="investment-committee",
            rationale=f"commit capital to {self._deal_id} (IC approval gate)",
            evidence={"ic_memo": underwriting.get("ic_memo")},
            correlation_id=self._correlation_id,
        )
        return {
            "committed": outcome.executed,
            "approval_id": outcome.request.id if outcome.request else None,
            "recommendation": recommendation,
        }


class PortfolioStewardshipSubagent(Subagent[None, dict[str, Any]]):
    """Standalone monitor: covenant/KPI early-warning on a held portfolio."""

    name = "portfolio-stewardship"

    def __init__(self, portfolio_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._portfolio_id = portfolio_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="monitor portfolio", tier=ModelTier.HAIKU)
        headroom = await _number(self._connectors, f"pm:covenant_headroom:{self._portfolio_id}")
        alerts = ["covenant"] if headroom < 0 else []
        return {"monitored": True, "covenant_headroom": headroom, "alerts": alerts}
