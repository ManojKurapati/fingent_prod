"""Insurance orchestrators (per ``claude2.md`` §7).

* :class:`InsuranceSubmissionOrchestrator` — **hybrid**: ``actuarial`` ‖
  ``cat-modelling`` fan out and join at ``underwriting`` (which evaluates the
  risk-appetite / accumulation gate).
* :class:`InsurancePortfolioOrchestrator` — **parallel**: ``reinsurance`` ‖
  ``product`` portfolio-level optimisation.
* :class:`InsuranceClaimsOrchestrator` — **sequential**: the post-bind claims
  lifecycle.
"""

from __future__ import annotations

from app.agents.core import (
    BaseOrchestrator,
    ClaudeGateway,
    OrchestrationMode,
    StepGraph,
    hybrid,
    parallel,
    sequential,
)
from app.agents.financial_services.insurance.schemas import (
    ClaimRequest,
    PortfolioRequest,
    SubmissionRequest,
)
from app.agents.financial_services.insurance.subagents import (
    ActuarialSubagent,
    CatModellingSubagent,
    ClaimsSubagent,
    ProductSubagent,
    ReinsuranceSubagent,
    UnderwritingSubagent,
)
from app.connectors import ToolRegistry


class InsuranceSubmissionOrchestrator(BaseOrchestrator[SubmissionRequest]):
    """Hybrid submission orchestrator: parallel pricing -> underwriting join."""

    group = "insurance"
    mode = OrchestrationMode.HYBRID

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._correlation_id = correlation_id

    def build_graph(self, request: SubmissionRequest) -> StepGraph:
        actuarial = ActuarialSubagent(
            request.region, request.tiv, self._gateway, self._connectors
        ).as_step()
        cat = CatModellingSubagent(
            request.peril, request.tiv, self._gateway, self._connectors
        ).as_step()
        underwriting = UnderwritingSubagent(
            request.region, request.peril, self._gateway, self._connectors
        ).as_step(depends_on=("actuarial", "cat-modelling"))
        return hybrid([actuarial, cat, underwriting])


class InsurancePortfolioOrchestrator(BaseOrchestrator[PortfolioRequest]):
    """Parallel portfolio orchestrator: reinsurance ‖ product."""

    group = "insurance"
    mode = OrchestrationMode.PARALLEL

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._correlation_id = correlation_id

    def build_graph(self, request: PortfolioRequest) -> StepGraph:
        reinsurance = ReinsuranceSubagent(request.region, self._gateway, self._connectors).as_step()
        product = ProductSubagent(request.product, self._gateway, self._connectors).as_step()
        return parallel([reinsurance, product])


class InsuranceClaimsOrchestrator(BaseOrchestrator[ClaimRequest]):
    """Sequential claims-lifecycle orchestrator (triage + reserve)."""

    group = "insurance"
    mode = OrchestrationMode.SEQUENTIAL

    def __init__(
        self,
        *,
        gateway: ClaudeGateway,
        connectors: ToolRegistry,
        correlation_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._connectors = connectors
        self._correlation_id = correlation_id

    def build_graph(self, request: ClaimRequest) -> StepGraph:
        claims = ClaimsSubagent(
            request.claim_id, request.amount, self._gateway, self._connectors
        ).as_step()
        return sequential([claims])
