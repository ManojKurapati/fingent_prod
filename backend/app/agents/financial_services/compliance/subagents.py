"""Compliance subagents — screening, disposition, continuous functions, and the
synchronous compliance gate this agent publishes to the rest of the firm.

Per-subject status comes from connectors (deterministic, fakeable). The
``fraud-investigation`` join dispositions any AML/sanctions hit and recommends a
SAR. Filing the SAR is consequential (:class:`FileSarTool`) and is gated from the
router. ``compliance_gate`` is the mandatory, fail-closed PASS/HOLD/DENY check
other agents call before client-facing, market, or filing actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry

_SCREEN_HITS = ("aml-kyc", "sanctions-screening")


async def _read(connectors: ToolRegistry, key: str) -> str | None:
    """Read a raw string value from the connector key/value store."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return str(raw) if raw is not None else None


async def _int(connectors: ToolRegistry, key: str) -> int:
    raw = await _read(connectors, key)
    return int(float(raw)) if raw is not None else 0


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Outcome of the synchronous compliance gate."""

    decision: str  # "PASS" | "HOLD" | "DENY"
    reason: str
    token: str | None


async def compliance_gate(connectors: ToolRegistry, subject: str) -> GateDecision:
    """Mandatory conduct/screening gate other agents call.

    Fail-closed: an unknown subject (no clearance record) is DENIED — a gate never
    defaults open. Returns a token only on PASS.
    """
    status = await _read(connectors, f"clearance:{subject}")
    if status == "clear":
        return GateDecision("PASS", "subject cleared", token=f"compliance-gate:{subject}")
    if status == "review":
        return GateDecision("HOLD", "subject under review", token=None)
    return GateDecision("DENY", f"subject not cleared (status={status})", token=None)


class FileSarTool(Tool[dict[str, Any], str]):
    """Consequential: file a suspicious-activity report with the FIU (external)."""

    name = "compliance_file_sar"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"filed-sar:{payload.get('subject')}"


class AmlKycSubagent(Subagent[None, dict[str, Any]]):
    """Parallel screen: CDD/EDD risk rating (conservative default = hit)."""

    name = "aml-kyc"

    def __init__(self, subject: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._subject = subject
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="aml kyc", tier=ModelTier.HAIKU)
        rating = await _read(self._connectors, f"kycrisk:{self._subject}") or "high"
        return {"subject": self._subject, "risk_rating": rating, "hit": rating == "high"}


class SanctionsScreeningSubagent(Subagent[None, dict[str, Any]]):
    """Parallel screen: count of sanctions-list matches."""

    name = "sanctions-screening"

    def __init__(self, subject: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._subject = subject
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="sanctions screen", tier=ModelTier.HAIKU)
        matches = await _int(self._connectors, f"sanctions:{self._subject}")
        return {"subject": self._subject, "matches": matches, "hit": matches > 0}


class FraudInvestigationSubagent(Subagent[None, dict[str, Any]]):
    """Disposition join: any screen hit blocks clearance and recommends a SAR."""

    name = "fraud-investigation"

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        hits = sorted(s for s in _SCREEN_HITS if ctx.results.get(s, {}).get("hit") is True)
        cleared = not hits
        return {
            "cleared": cleared,
            "escalated": bool(hits),
            "hits": hits,
            "sar_recommended": bool(hits),
        }


class ComplianceMonitoringSubagent(Subagent[None, dict[str, Any]]):
    """Continuous (parallel): second-line control testing + incident logging."""

    name = "compliance-monitoring"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="monitor controls", tier=ModelTier.HAIKU)
        incidents = await _int(self._connectors, "incidents")
        return {"open_incidents": incidents, "controls_tested": True}


class RegulatoryAffairsSubagent(Subagent[None, dict[str, Any]]):
    """Continuous (parallel): horizon-scan rules and track filings."""

    name = "regulatory-affairs"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="regulatory affairs", tier=ModelTier.HAIKU)
        filings = await _int(self._connectors, "filings")
        return {"pending_filings": filings}


class LegalCounselSubagent(Subagent[None, dict[str, Any]]):
    """Continuous (parallel): contract negotiation + legal-risk review."""

    name = "legal-counsel"

    def __init__(self, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="legal counsel", tier=ModelTier.HAIKU)
        contracts = await _int(self._connectors, "contracts")
        return {"contracts_under_review": contracts}
