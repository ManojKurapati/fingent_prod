"""Investment Banking subagents — one stateless worker per responsibility cluster.

Numeric/diligence inputs are pulled from connectors so the maths is deterministic
and testable with fakes; the Claude gateway drives the narrative/QA steps. The
only **consequential** action is the client-facing launch (send to client / market
launch), which is (a) denied outright unless the mandatory compliance gate clears
and (b) otherwise routed through the guardrail engine for human approval
(default-deny) rather than executed directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine

GATE_PASS = "PASS"
GATE_DENY = "DENY"


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


async def _text(connectors: ToolRegistry, key: str) -> str | None:
    """Fetch a string flag from the connector key/value store (None if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


class LaunchMandateTool(Tool[dict[str, Any], str]):
    """Consequential: send materials to the client / launch into the market.

    Communicating externally and launching a transaction on the firm's behalf is a
    consequential action, so it is gated by the guardrail engine and never invoked
    directly.
    """

    name = "ib_launch_mandate"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"launched:{payload.get('deal_id')}"


class CoverageOriginationSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: maintain sector coverage and qualify the mandate."""

    name = "coverage-origination"

    def __init__(self, deal_id: str, client: str, sector: str, gateway: ClaudeGateway) -> None:
        self._deal_id = deal_id
        self._client = client
        self._sector = sector
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="qualify mandate", tier=ModelTier.HAIKU)
        return {
            "qualified": True,
            "deal_id": self._deal_id,
            "client": self._client,
            "sector": self._sector,
            "note": resp.text,
        }


class ModelingDiligenceSubagent(Subagent[None, dict[str, Any]]):
    """Build the valuation pack (three-statement/DCF/LBO/comps) and review the data room."""

    name = "modeling-diligence"

    def __init__(self, deal_id: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._deal_id = deal_id
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="build model", tier=ModelTier.OPUS)
        ev = await _number(self._connectors, f"financials:{self._deal_id}")
        return {"enterprise_value": ev, "valuation_ready": True}


class MaterialsDraftingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel branch: draft pitch books / CIMs / board materials from the model."""

    name = "materials-drafting"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="draft materials", tier=ModelTier.HAIKU)
        ev = ctx.results["modeling-diligence"]["enterprise_value"]
        return {"deck_ready": True, "enterprise_value": ev}


class ComplianceGateSubagent(Subagent[None, dict[str, Any]]):
    """MANDATORY gate: conflicts check + MNPI/wall-crossing review before any send.

    Fail-closed — a missing or non-``clear`` conflict status denies the launch.
    """

    name = "compliance-gate"

    def __init__(self, client: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._client = client
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="review conflicts", tier=ModelTier.HAIKU)
        conflict = await _text(self._connectors, f"conflict:{self._client}")
        decision = GATE_PASS if conflict == "clear" else GATE_DENY
        ev = ctx.results["modeling-diligence"].get("enterprise_value", 0.0)
        return {
            "decision": decision,
            "client": self._client,
            "conflict": conflict,
            "enterprise_value": ev,
        }


class _ExecutionSubagent(Subagent[None, dict[str, Any]]):
    """Shared execution logic: gate-checked, default-deny client-facing launch.

    Concrete subclasses set ``name`` (the route segment) and ``kind`` (the deal
    family). The compliance gate's decision is consumed here: a deny blocks the
    launch outright (it never reaches the approval queue); a pass submits the
    consequential launch to the guardrail engine, which holds it for human sign-off.
    """

    kind: str

    def __init__(
        self, deal_id: str, guardrails: GuardrailEngine, *, correlation_id: str | None = None
    ) -> None:
        self._deal_id = deal_id
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = LaunchMandateTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        gate = ctx.results["compliance-gate"]
        if gate["decision"] != GATE_PASS:
            return {
                "kind": self.kind,
                "deal_id": self._deal_id,
                "blocked": True,
                "launched": False,
                "approval_id": None,
            }

        outcome = await self._guardrails.submit(
            self._tool,
            {"deal_id": self._deal_id, "kind": self.kind},
            actor="investment-banking",
            approver_role="compliance",
            rationale=f"{self.kind} launch for {gate.get('client')}",
            evidence={"enterprise_value": gate.get("enterprise_value", 0.0)},
            correlation_id=self._correlation_id,
        )
        return {
            "kind": self.kind,
            "deal_id": self._deal_id,
            "blocked": False,
            "launched": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }


class MaExecutionSubagent(_ExecutionSubagent):
    """Sell-side / buy-side M&A process execution."""

    name = "ma-execution"
    kind = "ma-execution"


class EcmDcmLevfinSubagent(_ExecutionSubagent):
    """ECM / DCM / leveraged-finance structuring, pricing, and book-building."""

    name = "ecm-dcm-levfin"
    kind = "ecm-dcm-levfin"


class RestructuringSubagent(_ExecutionSubagent):
    """Recap / debt-exchange / amend-and-extend restructuring execution."""

    name = "restructuring"
    kind = "restructuring"
