"""Finance Systems & Operations subagents — one worker per responsibility cluster.

Row counts, SoD-conflict flags and process KPIs are pulled from connectors so the
logic is deterministic and testable; the Claude gateway is used for narrative. The
only **consequential** action is applying an ERP access/config change that
introduces a segregation-of-duties conflict, which is routed through the guardrail
engine (default-deny) and never executed directly.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry
from app.guardrails import GuardrailEngine


async def _number(connectors: ToolRegistry, key: str) -> float | None:
    """Fetch a numeric value from the connector key/value store (None if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else None


async def _status(connectors: ToolRegistry, key: str) -> str | None:
    """Fetch a status string from the connector key/value store (None if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


class AccessChangeTool(Tool[dict[str, Any], str]):
    """Consequential: apply an ERP access/config change.

    A change that affects segregation of duties is gated by the guardrail engine
    (SoD review) and never invoked directly.
    """

    name = "finops_access_change"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"applied:{payload.get('change')}"


class DataPipelinesSubagent(Subagent[None, dict[str, Any]]):
    """Sequential spine head: extract, cleanse and reconcile financial data."""

    name = "data-pipelines"

    def __init__(
        self, sources: list[str], gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._sources = sources
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="run pipeline", tier=ModelTier.HAIKU)
        by_source: dict[str, float] = {}
        missing: list[str] = []
        for source in self._sources:
            rows = await _number(self._connectors, f"rows:{source}")
            if rows is None:
                missing.append(source)
            else:
                by_source[source] = rows
        return {
            "total_rows": sum(by_source.values()),
            "by_source": by_source,
            "reconciled": not missing,
            "missing": missing,
        }


class DashboardsReportingSubagent(Subagent[None, dict[str, Any]]):
    """Sequential spine tail: publish a dashboard catalog off reconciled data.

    Builds a per-source drilldown tile for every reconciled source plus the
    standard freshness/reconciliation/exceptions reporting tiles, and reports
    the metrics behind them — so the published set reflects the actual data,
    not a fixed list.
    """

    name = "dashboards-reporting"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="refresh dashboards", tier=ModelTier.HAIKU)
        pipeline = ctx.results["data-pipelines"]
        rows: float = pipeline["total_rows"]
        by_source: dict[str, float] = pipeline.get("by_source", {})
        reconciled: bool = pipeline.get("reconciled", True)
        missing: list[str] = pipeline.get("missing", [])
        anomaly = not reconciled or rows == 0

        source_tiles = [f"source:{s}" for s in sorted(by_source)]
        dashboards = [*source_tiles, "freshness", "reconciliation", "exceptions"]
        return {
            "dashboards": dashboards,
            "published": len(dashboards),
            "metrics": {
                "total_rows": rows,
                "sources": len(by_source),
                "missing_sources": len(missing),
            },
            "rows": rows,
            "anomaly": anomaly,
        }


class ErpAdministrationSubagent(Subagent[None, dict[str, Any]]):
    """Parallel lane: administer ERP access/config AND master data.

    Each requested change is typed via the connector. Master-data changes
    (vendor/customer/GL records) apply once their required fields validate and
    are rejected when incomplete; access/config changes apply directly unless
    they introduce a segregation-of-duties conflict, which is gated (default-deny).
    """

    name = "erp-administration"

    def __init__(
        self,
        access_changes: list[str],
        gateway: ClaudeGateway,
        guardrails: GuardrailEngine,
        connectors: ToolRegistry,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self._access_changes = access_changes
        self._gateway = gateway
        self._guardrails = guardrails
        self._connectors = connectors
        self._correlation_id = correlation_id
        self._tool = AccessChangeTool()

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="review access", tier=ModelTier.HAIKU)
        applied: list[str] = []
        master_data: list[str] = []
        rejected: list[str] = []
        conflicts: list[str] = []
        approval_ids: list[str] = []
        for change in self._access_changes:
            change_type = (await _status(self._connectors, f"change_type:{change}")) or "access"
            if change_type == "master_data":
                master_data.append(change)
                # Master-data record applies only once its required fields validate.
                if (await _status(self._connectors, f"md_complete:{change}")) == "yes":
                    applied.append(change)
                else:
                    rejected.append(change)
                continue
            if (await _status(self._connectors, f"sod_conflict:{change}")) != "yes":
                applied.append(change)
                continue
            conflicts.append(change)
            outcome = await self._guardrails.submit(
                self._tool,
                {"change": change},
                actor="finops",
                approver_role="sod-reviewer",
                rationale=f"access change {change!r} introduces a segregation-of-duties conflict",
                evidence={"change": change},
                correlation_id=self._correlation_id,
            )
            assert outcome.request is not None  # a consequential submit is always held
            approval_ids.append(outcome.request.id)
        return {
            "requested": len(self._access_changes),
            "applied": sorted(applied),
            "master_data_changes": sorted(master_data),
            "rejected": sorted(rejected),
            "conflicts": sorted(conflicts),
            "approval_ids": approval_ids,
            "gated": len(conflicts),
        }


class ProcessTransformationSubagent(Subagent[None, dict[str, Any]]):
    """Parallel lane: identify and prioritise automation opportunities."""

    name = "process-transformation"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="scan automation", tier=ModelTier.HAIKU)
        candidates = await _number(self._connectors, "automation:candidates") or 0.0
        opportunities = int(candidates)
        return {"opportunities": opportunities, "prioritised": opportunities > 0}


class O2cP2pProcessOwnerSubagent(Subagent[None, dict[str, Any]]):
    """Parallel lane: own O2C / P2P KPIs and drive improvement.

    Monitors cycle time and exceptions against target and turns breaches into
    concrete improvement actions (remediate exceptions, streamline cycle time)
    rather than only reporting the numbers.
    """

    name = "o2c-p2p-process-owner"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="monitor process KPIs", tier=ModelTier.HAIKU)
        cycle_time = await _number(self._connectors, "kpi:cycle_time") or 0.0
        exceptions = await _number(self._connectors, "kpi:exceptions") or 0.0
        target = await _number(self._connectors, "kpi:cycle_time_target")
        target = target if target is not None else 5.0

        recommendations: list[str] = []
        if exceptions > 0:
            recommendations.append("remediate-exceptions")
        if cycle_time > target:
            recommendations.append("streamline-cycle-time")
        return {
            "cycle_time": cycle_time,
            "exceptions": exceptions,
            "target": target,
            "over_target": cycle_time > target,
            "recommendations": recommendations,
            "action_required": bool(recommendations),
            "healthy": exceptions == 0,
        }
