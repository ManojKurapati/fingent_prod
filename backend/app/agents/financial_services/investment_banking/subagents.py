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
    """Sequential head: maintain sector coverage and tailor the pitch idea.

    Tailors the recommended product to the client relationship strength and
    sector momentum from the CRM/market connectors: positive sector momentum
    leans to a capital-markets idea, otherwise an M&A idea, and a strong
    relationship raises the priority.
    """

    name = "coverage-origination"

    def __init__(
        self,
        deal_id: str,
        client: str,
        sector: str,
        gateway: ClaudeGateway,
        connectors: ToolRegistry | None = None,
    ) -> None:
        self._deal_id = deal_id
        self._client = client
        self._sector = sector
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="qualify mandate", tier=ModelTier.HAIKU)
        rating = momentum = 0.0
        if self._connectors is not None:
            rating = await _number(self._connectors, f"client:rating:{self._client}")
            momentum = await _number(self._connectors, f"sector:momentum:{self._sector}")
        recommended = "ecm-dcm-levfin" if momentum > 0 else "ma-execution"
        return {
            "qualified": True,
            "deal_id": self._deal_id,
            "client": self._client,
            "sector": self._sector,
            "relationship_rating": rating,
            "sector_momentum": momentum,
            "recommended_product": recommended,
            "ideas": [recommended],
            "priority": "high" if rating >= 0.7 else "standard",
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
        ebitda = await _number(self._connectors, f"ebitda:{self._deal_id}")
        multiple = await _number(self._connectors, f"multiple:{self._deal_id}")
        net_debt = await _number(self._connectors, f"net_debt:{self._deal_id}")
        # EV from an EBITDA-multiple build when fundamentals are present; otherwise
        # fall back to a directly-supplied enterprise value.
        if ebitda > 0 and multiple > 0:
            ev = round(ebitda * multiple, 2)
            method = "ebitda-multiple"
        else:
            ev = await _number(self._connectors, f"financials:{self._deal_id}")
            method = "direct"
        return {
            "enterprise_value": ev,
            "equity_value": round(ev - net_debt, 2),
            "ebitda": ebitda,
            "multiple": multiple,
            "net_debt": net_debt,
            "method": method,
            "valuation_ready": True,
        }


class MaterialsDraftingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel branch: assemble the pitchbook / CIM / board materials from the model."""

    name = "materials-drafting"

    # Standard pitchbook section flow.
    _DECK_SECTIONS = (
        "cover",
        "executive-summary",
        "market-overview",
        "valuation",
        "transaction-structure",
        "next-steps",
    )

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="draft materials", tier=ModelTier.HAIKU)
        md = ctx.results["modeling-diligence"]
        ev = md["enterprise_value"]
        pitchbook = {
            "sections": list(self._DECK_SECTIONS),
            "page_count": len(self._DECK_SECTIONS),
            "valuation": {
                "enterprise_value": ev,
                "equity_value": md.get("equity_value"),
                "method": md.get("method"),
            },
        }
        return {"deck_ready": True, "enterprise_value": ev, "pitchbook": pitchbook}


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
