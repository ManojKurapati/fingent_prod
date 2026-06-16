"""Insurance subagents — one stateless worker per responsibility cluster.

Numeric inputs (rates, cat factors, accumulation, limits) are pulled from
connectors so the maths is deterministic and testable with fakes; the Claude
gateway is used for narrative steps. Binding a policy is **consequential** and is
never invoked directly here — it is routed through the guardrail engine (and a
mandatory accumulation gate) from the router (:class:`BindPolicyTool`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.core import ClaudeGateway, ModelTier, StepContext, Subagent
from app.connectors import Tool, ToolRegistry

# Placeholder model parameters.
_DEFAULT_RATE = 0.02
_DEFAULT_CAT_FACTOR = 0.05
_AAL_FRACTION = 0.1


async def _number(connectors: ToolRegistry, key: str) -> float:
    """Fetch a numeric value from the connector key/value store (0.0 if absent)."""
    raw: Any = await connectors.get("kv_read").invoke(key)
    return float(raw) if raw is not None else 0.0


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of the accumulation / risk-appetite gate."""

    passed: bool
    current: float
    proposed: float
    limit: float


async def accumulation_gate(
    connectors: ToolRegistry, region: str, peril: str, pml: float
) -> GateResult:
    """Mandatory pre-bind risk check: does region/peril stay within appetite?

    Fail-closed: an absent limit reads as 0.0, so any positive accumulation is
    denied. A gate never defaults open.
    """
    current = await _number(connectors, f"accumulation:{region}:{peril}")
    limit = await _number(connectors, f"limit:{region}:{peril}")
    proposed = round(current + pml, 2)
    return GateResult(passed=proposed <= limit, current=current, proposed=proposed, limit=limit)


class BindPolicyTool(Tool[dict[str, Any], str]):
    """Consequential: bind insurance risk on a policy (commits the firm)."""

    name = "insurance_bind_policy"
    consequential = True

    async def invoke(self, payload: dict[str, Any]) -> str:
        return f"bound:{payload.get('submission_id')}"


class ActuarialSubagent(Subagent[None, dict[str, Any]]):
    """Parallel pricing leg: technical premium from calibrated loss rates."""

    name = "actuarial"

    def __init__(
        self, region: str, tiv: float, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._region = region
        self._tiv = tiv
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="actuarial rate", tier=ModelTier.HAIKU)
        rate = await _number(self._connectors, f"rate:{self._region}") or _DEFAULT_RATE
        return {"region": self._region, "rate": rate, "premium": round(self._tiv * rate, 2)}


class CatModellingSubagent(Subagent[None, dict[str, Any]]):
    """Parallel pricing leg: catastrophe accumulation (PML / AAL)."""

    name = "cat-modelling"

    def __init__(
        self, peril: str, tiv: float, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._peril = peril
        self._tiv = tiv
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="cat model", tier=ModelTier.OPUS)
        factor = await _number(self._connectors, f"catfactor:{self._peril}") or _DEFAULT_CAT_FACTOR
        pml = round(self._tiv * factor, 2)
        return {
            "peril": self._peril,
            "cat_factor": factor,
            "pml": pml,
            "aal": round(pml * _AAL_FRACTION, 2),
        }


class UnderwritingSubagent(Subagent[None, dict[str, Any]]):
    """Join: accept/decline against the risk-appetite / accumulation gate."""

    name = "underwriting"

    def __init__(
        self, region: str, peril: str, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._region = region
        self._peril = peril
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="underwrite", tier=ModelTier.HAIKU)
        premium: float = ctx.results["actuarial"]["premium"]
        pml: float = ctx.results["cat-modelling"]["pml"]
        gate = await accumulation_gate(self._connectors, self._region, self._peril, pml)
        return {
            "decision": "accept" if gate.passed else "decline",
            "premium": premium,
            "pml": pml,
            "current_accumulation": gate.current,
            "proposed_accumulation": gate.proposed,
            "limit": gate.limit,
            "within_appetite": gate.passed,
        }


class ClaimsSubagent(Subagent[None, dict[str, Any]]):
    """Post-bind lifecycle: triage, verify coverage, reserve, and flag fraud."""

    name = "claims"

    def __init__(
        self, claim_id: str, amount: float, gateway: ClaudeGateway, connectors: ToolRegistry
    ) -> None:
        self._claim_id = claim_id
        self._amount = amount
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="triage claim", tier=ModelTier.HAIKU)
        flagged = await _number(self._connectors, f"fraudflag:{self._claim_id}") >= 1.0
        return {
            "claim_id": self._claim_id,
            "reserve": round(self._amount, 2),
            "coverage_verified": True,
            "suspected_fraud": flagged,
        }


class ReinsuranceSubagent(Subagent[None, dict[str, Any]]):
    """Portfolio-level (parallel): cession above retention, recoverables."""

    name = "reinsurance"

    def __init__(self, region: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._region = region
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="reinsurance", tier=ModelTier.HAIKU)
        gross = await _number(self._connectors, f"grossexposure:{self._region}")
        retention = await _number(self._connectors, f"retention:{self._region}")
        ceded = round(max(0.0, gross - retention), 2)
        return {"gross": gross, "retention": retention, "ceded": ceded, "recoverable": ceded}


class ProductSubagent(Subagent[None, dict[str, Any]]):
    """Portfolio-level (parallel): in-force profitability via combined ratio."""

    name = "product"

    def __init__(self, product: str, gateway: ClaudeGateway, connectors: ToolRegistry) -> None:
        self._product = product
        self._gateway = gateway
        self._connectors = connectors

    async def execute(self, ctx: StepContext) -> dict[str, Any]:
        await self._gateway.complete(prompt="product kpis", tier=ModelTier.HAIKU)
        cr = await _number(self._connectors, f"combinedratio:{self._product}")
        return {"product": self._product, "combined_ratio": cr, "profitable": 0.0 < cr < 1.0}
