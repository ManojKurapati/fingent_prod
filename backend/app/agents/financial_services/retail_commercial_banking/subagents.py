"""Retail & Commercial Banking subagents — the lending pipeline workers.

Applicant financials (income, debt service, collateral) are pulled from connectors
so the underwriting ratios are deterministic; the Claude gateway is used for
narrative steps. The single **consequential** action — funding/disbursing the loan
— is routed through the guardrail engine (default-deny) and is only proposed when
the underwriting decision clears the credit policy.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

# Credit-policy / risk-appetite ceilings.
_MAX_DSR = 0.4  # debt-service-to-income
_MAX_LTV = 0.8  # loan-to-value


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class FundLoanTool(Tool[dict[str, Any], str]):
    """Consequential: disburse/fund an approved loan (extends credit)."""

    name = "banking_fund_loan"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"funded:{payload.get('application_id')}"


class _IntakeSubagent(Subagent[None, dict[str, Any]]):
    """Shared base for the three independent intake channels."""

    channel: str

    def __init__(self, applicant: str, gateway: ClaudeGateway) -> None:
        self._applicant = applicant
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt=f"intake {self.channel}", tier=ModelTier.HAIKU)
        return {"channel": self.channel, "applicant": self._applicant, "intake": True}


class PersonalBankingSubagent(_IntakeSubagent):
    """Retail intake: open/serve a personal customer and refer to lending."""

    name = "personal-banking"
    channel = "personal"


class CommercialRmSubagent(_IntakeSubagent):
    """Commercial intake: relationship manager originates a business facility."""

    name = "commercial-rm"
    channel = "commercial"


class BranchOpsSubagent(_IntakeSubagent):
    """Branch intake: walk-in/branch-originated application."""

    name = "branch-ops"
    channel = "branch"


class LoanOriginationSubagent(Subagent[None, dict[str, Any]]):
    """Collect documentation and pre-qualify the applicant."""

    name = "loan-origination"

    def __init__(
        self, application_id: str, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._application_id = application_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="originate loan", tier=ModelTier.HAIKU)
        income = await _number(self._connectors, f"bank:income:{self._application_id}")
        return {
            "application_id": self._application_id,
            "pre_qualified": income > 0.0,
            "income": income,
        }


class CreditAnalysisSubagent(Subagent[None, dict[str, Any]]):
    """Assign a risk rating from income vs existing debt service."""

    name = "credit-analysis"

    def __init__(
        self, application_id: str, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._application_id = application_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="analyse credit", tier=ModelTier.HAIKU)
        income = await _number(self._connectors, f"bank:income:{self._application_id}")
        debt_service = await _number(self._connectors, f"bank:debt_service:{self._application_id}")
        ratio = debt_service / income if income else 1.0
        rating = "A" if ratio <= 0.25 else "B" if ratio <= 0.5 else "C"
        return {"risk_rating": rating, "existing_dsr": ratio}


class UnderwritingSubagent(Subagent[None, dict[str, Any]]):
    """Credit-policy gate: verify ratios and decide approve/decline against appetite."""

    name = "underwriting"

    def __init__(
        self,
        application_id: str,
        loan_amount: float,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
    ) -> None:
        self._application_id = application_id
        self._loan_amount = loan_amount
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="underwrite application", tier=ModelTier.OPUS)
        income = await _number(self._connectors, f"bank:income:{self._application_id}")
        debt_service = await _number(self._connectors, f"bank:debt_service:{self._application_id}")
        collateral = await _number(self._connectors, f"bank:collateral:{self._application_id}")
        dsr = debt_service / income if income else float("inf")
        ltv = self._loan_amount / collateral if collateral else float("inf")
        approve = dsr <= _MAX_DSR and ltv <= _MAX_LTV
        return {
            "decision": "approve" if approve else "decline",
            "dsr": dsr,
            "ltv": ltv,
            "application_id": self._application_id,
        }


class LoanFundingSubagent(Subagent[None, dict[str, Any]]):
    """Consequential disbursement: blocked unless underwriting approved."""

    name = "loan-funding"

    def __init__(
        self, application_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._application_id = application_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = FundLoanTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        if ctx.results["underwriting"]["decision"] != "approve":
            return {"funded": False, "blocked": True, "approval_id": None}
        outcome = await self._guardrails.submit(
            self._tool,
            {"application_id": self._application_id},
            actor="retail-commercial-banking",
            approver_role="underwriter",
            rationale=f"fund approved loan {self._application_id}",
            correlation_id=self._correlation_id,
        )
        return {
            "funded": outcome.executed,
            "blocked": False,
            "approval_id": outcome.request.id if outcome.request else None,
        }
