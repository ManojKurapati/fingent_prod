"""Internal Audit subagents — one stateless worker per responsibility cluster.

Control evidence and SOX effectiveness statuses are pulled from connectors (which
stand in for the shared audit log / control matrix) so the pass/fail logic is
deterministic and testable; the Claude gateway is used for narrative/scoping. The
only **consequential** action is issuing (publishing) the audit report, which is
routed through the guardrail engine (default-deny) and never executed directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine


async def _status(connectors: ToolRegistry, key: str) -> str | None:
    """Fetch a status string from the connector key/value store (None if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


class PublishFindingsTool(Tool[dict[str, Any], str]):
    """Consequential: issue (publish) the audit report / findings.

    Issuing an assurance report is an external communication, so it is gated by
    the guardrail engine (CAE approval) and never invoked directly.
    """

    name = "audit_publish_findings"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"published:{payload.get('engagement')}"


class AuditPlanningSubagent(Subagent[None, dict[str, Any]]):
    """Sequential head: build the risk-based annual plan and scope the engagement.

    Each control carries an inherent-risk score from the connector (the risk
    register). The plan risk-ranks the control universe and flags the controls
    at/above ``risk_threshold`` as priority coverage for the cycle, so testing
    effort is steered by risk rather than treating every control equally.
    """

    name = "audit-planning"

    def __init__(
        self,
        engagement: str,
        controls: list[str],
        gateway: ClaudeGateway,
        connectors: ToolRegistry | None = None,
        *,
        risk_threshold: float = 0.5,
    ) -> None:
        self._engagement = engagement
        self._controls = controls
        self._gateway = gateway
        self._connectors = connectors
        self._risk_threshold = risk_threshold

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        resp = await self._gateway.complete(prompt="scope audit plan", tier=ModelTier.OPUS)
        risk_scores: dict[str, float] = {}
        if self._connectors is not None:
            risk_scores = {
                c: await _number(self._connectors, f"risk:{c}") for c in self._controls
            }
        risk_ranked = sorted(self._controls, key=lambda c: (-risk_scores.get(c, 0.0), c))
        priority = [c for c in risk_ranked if risk_scores.get(c, 0.0) >= self._risk_threshold]
        return {
            "engagement": self._engagement,
            "scope": list(self._controls),
            "risk_scores": risk_scores,
            "risk_ranked": risk_ranked,
            "priority_controls": priority,
            "planned": True,
            "note": resp.text,
        }


class ControlTestSubagent(Subagent[None, dict[str, Any]]):
    """Parallel testing stage: execute one control test and gather its evidence."""

    def __init__(self, control: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self.name = f"control-test:{control}"
        self._control = control
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="test control", tier=ModelTier.HAIKU)
        evidence = await _status(self._connectors, f"evidence:{self._control}")
        passed = evidence == "pass"
        return {
            "control": self._control,
            "evidence": evidence,
            "passed": passed,
            "deficiency": not passed,
        }


class SoxControlsSubagent(Subagent[None, dict[str, Any]]):
    """Parallel testing stage: assess SOX control design + operating effectiveness."""

    name = "sox-controls"

    def __init__(
        self, controls: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._controls = controls
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="assess SOX matrix", tier=ModelTier.HAIKU)
        deficiencies = [
            c
            for c in self._controls
            if (await _status(self._connectors, f"sox:{c}")) != "effective"
        ]
        return {
            "assessed": len(self._controls),
            "deficiencies": sorted(deficiencies),
            "severity": "high" if deficiencies else "none",
        }


class FindingsReportingSubagent(Subagent[None, dict[str, Any]]):
    """Fan-in: synthesise gaps and gate the report issuance behind CAE approval."""

    name = "findings-reporting"

    def __init__(
        self,
        engagement: str,
        guardrails: GuardrailEngine,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._engagement = engagement
        self._guardrails = guardrails
        self._correlation_id = correlation_id
        self._tool = PublishFindingsTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        control_failures = sorted(
            v["control"]
            for k, v in ctx.results.items()
            if k.startswith("control-test:") and v.get("deficiency")
        )
        sox_deficiencies = list(ctx.results.get("sox-controls", {}).get("deficiencies", []))
        findings = sorted(set(control_failures) | set(sox_deficiencies))

        # Issuing an assurance report is consequential: default-deny until the CAE
        # approves. It is held, never auto-published.
        outcome = await self._guardrails.submit(
            self._tool,
            {"engagement": self._engagement, "findings": findings},
            actor="audit",
            approver_role="cae",
            rationale=f"issue audit report for {self._engagement} ({len(findings)} findings)",
            evidence={"control_failures": control_failures, "sox_deficiencies": sox_deficiencies},
            correlation_id=self._correlation_id,
        )
        return {
            "engagement": self._engagement,
            "control_failures": control_failures,
            "sox_deficiencies": sorted(sox_deficiencies),
            "findings": findings,
            "published": outcome.executed,
            "approval_id": outcome.request.id if outcome.request else None,
        }


class RemediationTrackingSubagent(Subagent[None, dict[str, Any]]):
    """Sequential tail: open remediation items for findings and track to closure.

    Each finding's remediation status is read from the connector (the issue
    tracker): a finding marked ``closed`` is retired, anything else stays open.
    The engagement only reaches ``closed`` once every finding is remediated.
    """

    name = "remediation-tracking"

    def __init__(self, connectors: ToolRegistry | None = None) -> None:
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        findings = list(ctx.results.get("findings-reporting", {}).get("findings", []))
        statuses: dict[str, str] = {}
        for finding in findings:
            status = None
            if self._connectors is not None:
                status = await _status(self._connectors, f"remediation:{finding}")
            statuses[finding] = status or "open"

        closed_items = sorted(f for f, st in statuses.items() if st == "closed")
        open_items = sorted(f for f, st in statuses.items() if st != "closed")
        if not findings:
            overall = "clean"
        elif not open_items:
            overall = "closed"
        else:
            overall = "tracking"
        return {
            "open": len(open_items),
            "items": open_items,
            "closed": len(closed_items),
            "closed_items": closed_items,
            "statuses": statuses,
            "status": overall,
        }
