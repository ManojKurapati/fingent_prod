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
    """Sequential spine tail: render dashboards off reconciled data, flag anomalies."""

    name = "dashboards-reporting"

    def __init__(self, gateway: ClaudeGateway) -> None:
        self._gateway = gateway

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="refresh dashboards", tier=ModelTier.HAIKU)
        pipeline = ctx.results["data-pipelines"]
        rows: float = pipeline["total_rows"]
        anomaly = not pipeline["reconciled"] or rows == 0
        return {
            "dashboards": ["freshness", "reconciliation"],
            "rows": rows,
            "anomaly": anomaly,
        }


class ErpAdministrationSubagent(Subagent[None, dict[str, Any]]):
    """Parallel lane: process ERP access/config changes; SoD conflicts are gated."""

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
        conflicts: list[str] = []
        approval_ids: list[str] = []
        for change in self._access_changes:
            if (await _status(self._connectors, f"sod_conflict:{change}")) != "yes":
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
    """Parallel lane: monitor end-to-end O2C / P2P process KPIs."""

    name = "o2c-p2p-process-owner"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="monitor process KPIs", tier=ModelTier.HAIKU)
        cycle_time = await _number(self._connectors, "kpi:cycle_time") or 0.0
        exceptions = await _number(self._connectors, "kpi:exceptions") or 0.0
        return {
            "cycle_time": cycle_time,
            "exceptions": exceptions,
            "healthy": exceptions == 0,
        }
