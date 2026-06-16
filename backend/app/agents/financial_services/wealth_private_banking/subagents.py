"""Wealth & Private Banking subagents — one worker per responsibility cluster.

Client risk/collateral inputs are pulled from connectors so suitability and credit
maths is deterministic; the Claude gateway is used for narrative steps. The two
**consequential** actions — moving client assets (rebalance) and extending credit
(Lombard) — are routed through the guardrail engine (default-deny) and are reached
only after their suitability/credit gate PASSes.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Lombard lending ceiling: facility may not exceed this fraction of collateral.
_MAX_LTV = 0.5


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class RebalanceTool(Tool[dict[str, Any], str]):
    """Consequential: move client assets to implement a discretionary rebalance."""

    name = "wealth_rebalance"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"rebalanced:{payload.get('client_id')}"


class ExtendCreditTool(Tool[dict[str, Any], str]):
    """Consequential: extend a Lombard/credit facility against client assets."""

    name = "wealth_extend_credit"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"lent:{payload.get('client_id')}"


class ClientOnboardingKycSubagent(Subagent[None, dict[str, Any]]):
    """Sequential entry gate: onboard the client and clear KYC/suitability."""

    name = "client-onboarding-kyc"

    def __init__(self, client_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._client_id = client_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="onboard kyc", tier=ModelTier.HAIKU)
        hit = await _number(self._connectors, f"wealth:sanctions_hit:{self._client_id}")
        return {"client_id": self._client_id, "kyc_cleared": hit == 0.0}


class FinancialPlanningSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: build a comprehensive plan once KYC has cleared."""

    name = "financial-planning"

    def __init__(self, client_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._client_id = client_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        if not ctx.results["client-onboarding-kyc"]["kyc_cleared"]:
            return {"skipped": True}
        await self._gateway.complete(prompt="financial planning", tier=ModelTier.HAIKU)
        net_worth = await _number(self._connectors, f"wealth:net_worth:{self._client_id}")
        return {"skipped": False, "plan": {"goal": "retirement", "net_worth": net_worth}}


class InvestmentAdviceSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out: translate the house view into client-specific advice."""

    name = "investment-advice"

    def __init__(self, client_id: str, gateway: ClaudeGateway) -> None:
        self._client_id = client_id
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        if not ctx.results["client-onboarding-kyc"]["kyc_cleared"]:
            return {"skipped": True}
        await self._gateway.complete(prompt="investment advice", tier=ModelTier.HAIKU)
        return {"skipped": False, "allocation": {"equity": 0.6, "bond": 0.4}}


class PlanReconciliationSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: reconcile the plan and the target allocation into one proposal."""

    name = "plan-reconciliation"

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        planning = ctx.results.get("financial-planning", {})
        advice = ctx.results.get("investment-advice", {})
        reconciled = not planning.get("skipped", True) and not advice.get("skipped", True)
        return {"reconciled": reconciled}


class SuitabilityGateSubagent(Subagent[None, dict[str, Any]]):
    """Mandatory suitability gate before any discretionary portfolio change."""

    name = "suitability-gate"

    def __init__(self, client_id: str, proposed_risk: float, connectors: ToolRegistry) -> None:
        self._client_id = client_id
        self._proposed_risk = proposed_risk
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        tolerance = await _number(self._connectors, f"wealth:risk_tolerance:{self._client_id}")
        decision = "PASS" if self._proposed_risk <= tolerance else "DENY"
        return {"decision": decision, "tolerance": tolerance, "proposed_risk": self._proposed_risk}


class CreditGateSubagent(Subagent[None, dict[str, Any]]):
    """Mandatory suitability + credit gate before extending a Lombard facility."""

    name = "credit-gate"

    def __init__(self, client_id: str, loan_amount: float, connectors: ToolRegistry) -> None:
        self._client_id = client_id
        self._loan_amount = loan_amount
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        collateral = await _number(self._connectors, f"wealth:collateral:{self._client_id}")
        ltv = self._loan_amount / collateral if collateral else float("inf")
        decision = "PASS" if ltv <= _MAX_LTV else "DENY"
        return {"decision": decision, "ltv": ltv}


class DiscretionaryPmSubagent(Subagent[None, dict[str, Any]]):
    """Consequential rebalance: blocked unless the suitability gate PASSes."""

    name = "discretionary-pm"

    def __init__(
        self, client_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._client_id = client_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = RebalanceTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        if ctx.results["suitability-gate"]["decision"] != "PASS":
            return {"executed": False, "blocked": True, "approval_id": None}
        outcome = await self._guardrails.submit(
            self._tool,
            {"client_id": self._client_id},
            actor="wealth-private-banking",
            approver_role="advisor",
            rationale=f"rebalance discretionary book for {self._client_id}",
            correlation_id=self._correlation_id,
        )
        return {
            "executed": outcome.executed,
            "blocked": False,
            "approval_id": outcome.request.id if outcome.request else None,
        }


class PrivateBankingSubagent(Subagent[None, dict[str, Any]]):
    """Consequential credit extension: blocked unless the credit gate PASSes."""

    name = "private-banking"

    def __init__(
        self,
        client_id: str,
        loan_amount: float,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._client_id = client_id
        self._loan_amount = loan_amount
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = ExtendCreditTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        if ctx.results["credit-gate"]["decision"] != "PASS":
            return {"executed": False, "blocked": True, "approval_id": None}
        outcome = await self._guardrails.submit(
            self._tool,
            {"client_id": self._client_id, "amount": self._loan_amount},
            actor="wealth-private-banking",
            approver_role="private-banker",
            rationale=f"extend {self._loan_amount} Lombard facility to {self._client_id}",
            correlation_id=self._correlation_id,
        )
        return {
            "executed": outcome.executed,
            "blocked": False,
            "approval_id": outcome.request.id if outcome.request else None,
        }
