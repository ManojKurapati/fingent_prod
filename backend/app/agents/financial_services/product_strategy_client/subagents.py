"""Product/Strategy/Client subagents — one stateless worker per responsibility.

Pricing economics are pulled from connectors so the maths is deterministic and
testable with fakes; the Claude gateway drives discovery/narrative. The two
**consequential** actions — launching a product (gated by compliance/regulatory
filing) and activating a client (gated by KYC) — are refused outright when their
gate has not cleared, and otherwise routed through the guardrail engine
(default-deny).
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


class ProductLaunchTool(Tool[dict[str, Any], str]):
    """Consequential: take a product live (external filing / go-live)."""

    name = "product_launch"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"launched:{payload.get('initiative')}"


class ClientActivationTool(Tool[dict[str, Any], str]):
    """Consequential: activate an onboarded client (entitlements / connectivity)."""

    name = "product_activate_client"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"activated:{payload.get('client_id')}"


class ProductManagementSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: discovery and requirements for the initiative."""

    name = "product-management"

    def __init__(self, initiative: str, gateway: ClaudeGateway) -> None:
        self._initiative = initiative
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="run discovery", tier=ModelTier.HAIKU)
        return {"initiative": self._initiative, "requirements_ready": True, "note": resp.text}


class PricingSubagent(Subagent[None, dict[str, Any]]):
    """Model the economics: mark cost up by the target margin."""

    name = "pricing"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="model pricing", tier=ModelTier.HAIKU)
        cost = await _number(self._connectors, "pricing:cost")
        margin = await _number(self._connectors, "pricing:margin")
        return {"cost": cost, "margin": margin, "price": round(cost * (1 + margin), 2)}


class ComplianceFilingGateSubagent(Subagent[None, dict[str, Any]]):
    """Mandatory pre-launch gate: compliance/regulatory-filing clearance token."""

    name = "compliance-filing"

    def __init__(self, initiative: str, token: str | None, connectors: ToolRegistry) -> None:
        self._initiative = initiative
        self._token = token
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        passed = False
        if self._token:
            verdict = await self._connectors.get("kv_read").invoke(f"filing:{self._token}")
            passed = verdict == "cleared"
        return {
            "initiative": self._initiative,
            "token": self._token,
            "passed": passed,
            "reason": "filing cleared" if passed else "no cleared filing",
        }


class LaunchSubagent(Subagent[None, dict[str, Any]]):
    """Take the product live — only after the filing gate clears (consequential)."""

    name = "launch"

    def __init__(
        self,
        initiative: str,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._initiative = initiative
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = ProductLaunchTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        gate: dict[str, Any] = ctx.results["compliance-filing"]
        if not gate["passed"]:
            # Fail-closed: an unfiled product is never launched, never submitted.
            return {
                "blocked": True,
                "executed": False,
                "approval_id": None,
                "reason": "compliance-filing gate did not pass",
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"initiative": self._initiative},
            actor="product",
            approver_role="cpo",
            rationale=f"launch product {self._initiative}",
            evidence={"initiative": self._initiative, "filing_token": gate.get("token")},
            correlation_id=self._correlation_id,
        )
        return {
            "blocked": False,
            "executed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }


class SalesDistributionSubagent(Subagent[None, dict[str, Any]]):
    """Parallel commercial loop: own the pipeline across channels."""

    name = "sales-distribution"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="run pipeline", tier=ModelTier.HAIKU)
        return {"workstream": self.name, "summary": resp.text}


class ClientServicesSubagent(Subagent[None, dict[str, Any]]):
    """Parallel commercial loop: relationship health and retention."""

    name = "client-services"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="service client", tier=ModelTier.HAIKU)
        return {"workstream": self.name, "summary": resp.text}


class ClientOnboardingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel commercial loop: activate a client only after KYC clears (consequential)."""

    name = "client-onboarding"

    def __init__(
        self,
        client_id: str,
        kyc_token: str | None,
        guardrails: GuardrailEngine,
        connectors: ToolRegistry,
        gateway: ClaudeGateway,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._client_id = client_id
        self._kyc_token = kyc_token
        self._guardrails = guardrails
        self._connectors = connectors
        self._gateway = gateway
        self._correlation_id = correlation_id
        self._tool = ClientActivationTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="onboard client", tier=ModelTier.HAIKU)
        cleared = False
        if self._kyc_token:
            verdict = await self._connectors.get("kv_read").invoke(f"kyc:{self._kyc_token}")
            cleared = verdict == "cleared"

        if not cleared:
            # Fail-closed: no client is activated before KYC clears.
            return {
                "workstream": self.name,
                "blocked": True,
                "executed": False,
                "approval_id": None,
                "reason": "KYC not cleared",
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"client_id": self._client_id},
            actor="product",
            approver_role="onboarding-lead",
            rationale=f"activate client {self._client_id}",
            evidence={"client_id": self._client_id, "kyc_token": self._kyc_token},
            correlation_id=self._correlation_id,
        )
        return {
            "workstream": self.name,
            "blocked": False,
            "executed": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }
