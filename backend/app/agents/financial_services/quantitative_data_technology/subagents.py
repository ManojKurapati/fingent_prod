"""Quant/Data/Tech subagents — one stateless worker per responsibility cluster.

The six research workstreams produce candidate models/strategies (narrative via
the Claude gateway). The only **consequential** action is promoting a candidate
to production / live trading; it is refused unless an independent
model-validation gate clears, and otherwise routed through the guardrail engine
(default-deny).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine


class ModelPromotionTool(Tool[dict[str, Any], str]):
    """Consequential: promote a validated model/strategy to the production library.

    Deploying to production / live trading is a consequential action, so it is
    gated by the guardrail engine and never invoked directly.
    """

    name = "quant_promote_model"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"promoted:{payload.get('model_id')}"


class _WorkstreamSubagent(Subagent[None, dict[str, Any]]):
    """Base for an independent research workstream that emits a candidate artifact."""

    name: str
    prompt: str

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt=self.prompt, tier=ModelTier.HAIKU)
        return {"workstream": self.name, "candidate": True, "summary": resp.text}


class QuantPricingSubagent(_WorkstreamSubagent):
    """Pricing/valuation models for derivatives and structured products."""

    name = "quant-pricing"
    prompt = "price derivatives"


class QuantResearchSubagent(_WorkstreamSubagent):
    """Alpha-signal hypotheses, feature engineering, and cost-aware backtests."""

    name = "quant-research"
    prompt = "research alpha"


class RiskModelDevSubagent(_WorkstreamSubagent):
    """PD/LGD/VaR/economic-capital models and regulatory methodologies."""

    name = "risk-model-dev"
    prompt = "develop risk model"


class DataScienceSubagent(_WorkstreamSubagent):
    """Predictive/classification models for churn/default/fraud."""

    name = "data-science"
    prompt = "score data"


class FinancialEngineeringSubagent(_WorkstreamSubagent):
    """Bespoke payoffs, cash-flow/pricing engines, hedging/replication."""

    name = "financial-engineering"
    prompt = "engineer product"


class SystematicDevSubagent(_WorkstreamSubagent):
    """Automated strategies and execution algos with kill-switch monitoring."""

    name = "systematic-dev"
    prompt = "build strategy"


class ModelValidationGateSubagent(Subagent[None, dict[str, Any]]):
    """Mandatory pre-production gate: an independent (Risk Agent) validation token.

    Promotion cannot proceed without a present, **approved** validation token —
    research -> validation -> production is strictly ordered.
    """

    name = "model-validation"

    def __init__(self, model_id: str, token: str | None, connectors: ToolRegistry) -> None:
        self._model_id = model_id
        self._token = token
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        passed = False
        if self._token:
            verdict = await self._connectors.get("kv_read").invoke(f"validation:{self._token}")
            passed = verdict == "approved"
        return {
            "model_id": self._model_id,
            "token": self._token,
            "passed": passed,
            "reason": "validation token approved" if passed else "no approved validation token",
        }


class PromoteSubagent(Subagent[None, dict[str, Any]]):
    """Promote a candidate to production — only after validation clears (consequential)."""

    name = "promote"

    def __init__(
        self,
        model_id: str,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = ModelPromotionTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        gate: dict[str, Any] = ctx.results["model-validation"]
        if not gate["passed"]:
            # Fail-closed: an unvalidated model is never promoted, never submitted.
            return {
                "blocked": True,
                "executed": False,
                "approval_id": None,
                "reason": "model-validation gate did not pass",
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"model_id": self._model_id},
            actor="quant",
            approver_role="head-of-quant",
            rationale=f"promote validated model {self._model_id} to production",
            evidence={"model_id": self._model_id, "validation_token": gate.get("token")},
            correlation_id=self._correlation_id,
        )
        return {
            "blocked": False,
            "executed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }
