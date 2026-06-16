"""Example subagents for the template group-agent.

Each subagent is a stateless worker: it receives a :class:`StepContext` (with its
dependencies' outputs), calls shared services (the Claude gateway, connectors, the
guardrail engine), and returns a typed output. Consequential actions are NEVER
executed directly — they are routed through the guardrail engine, which holds them
for human approval (default-deny).

COPY THIS FILE. Replace these three subagents with your group's real ones.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool
from app.guardrails import GuardrailEngine


class PublishTool(Tool[dict[str, Any], str]):
    """A stand-in consequential tool (e.g. 'file externally' / 'post to ledger')."""

    name = "template_publish"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"published:{payload.get('pack')}"


class IntakeSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: validate inputs before any modelling runs."""

    name = "data-intake"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="validate intake", tier=ModelTier.HAIKU)
        return {"validated": True, "note": resp.text}


class AnalyzeSubagent(Subagent[None, dict[str, Any]]):
    """Parallel fan-out worker: one independent unit of analysis (per cost centre)."""

    def __init__(self, cost_centre: str, gateway: ClaudeGateway) -> None:
        self.name = f"analyze:{cost_centre}"
        self._cost_centre = cost_centre
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        assert ctx.results["data-intake"]["validated"] is True
        resp = await self._gateway.complete(
            prompt=f"analyze {self._cost_centre}", tier=ModelTier.HAIKU
        )
        return {"cost_centre": self._cost_centre, "summary": resp.text}


class ReportSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: assemble the pack, then route the consequential publish to the gate."""

    name = "reporting-pack"

    def __init__(self, guardrails: GuardrailEngine, *, correlation_id: str | None = None) -> None:
        self._guardrails = guardrails
        self._publish = PublishTool()
        self._correlation_id = correlation_id

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        analyses = [v for k, v in ctx.results.items() if k.startswith("analyze:")]
        pack = {"sections": len(analyses)}
        # Consequential: do NOT publish directly — submit for human approval.
        outcome = await self._guardrails.submit(
            self._publish,
            {"pack": pack},
            actor="template",
            approver_role="controller",
            rationale="publish template reporting pack",
            correlation_id=self._correlation_id,
        )
        return {
            "pack": pack,
            "published": outcome.executed,  # False until approved
            "approval_id": outcome.request.id if outcome.request else None,
        }
