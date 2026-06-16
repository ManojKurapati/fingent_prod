"""Orchestrator-graph tests for Product, Strategy & Client.

The initiative path is SEQUENTIAL: ``product-management -> pricing ->
compliance-filing -> launch`` — discovery feeds pricing, and the mandatory
compliance/regulatory-filing gate precedes the consequential launch. The
post-launch commercial loop is PARALLEL (``sales-distribution`` ‖
``client-onboarding`` ‖ ``client-services``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.product_strategy_client.orchestrator import (
    ProductCommercialOrchestrator,
    ProductInitiativeOrchestrator,
)
from app.agents.financial_services.product_strategy_client.schemas import (
    CommercialRequest,
    InitiativeRequest,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_COMMERCIAL_PROMPTS = {"run pipeline", "onboard client", "service client"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _connectors(**data: str) -> ToolRegistry:
    return build_fake_connector(store=FakeStore(data=dict(data)))


def _initiative(connectors: ToolRegistry) -> tuple[ProductInitiativeOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = ProductInitiativeOrchestrator(
        gateway=ClaudeGateway(transport=_stub), guardrails=guardrails, connectors=connectors
    )
    return orch, guardrails


def _commercial(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[ProductCommercialOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = ProductCommercialOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _connectors(),
    )
    return orch, guardrails


def test_initiative_graph_is_sequential() -> None:
    orch, _ = _initiative(_connectors(**{"pricing:cost": "100", "pricing:margin": "0.25"}))
    graph = orch.build_graph(InitiativeRequest(name="FX-Hedge", filing_token="FT-1"))
    assert graph.mode is OrchestrationMode.SEQUENTIAL
    assert [s.name for s in graph.steps] == [
        "product-management",
        "pricing",
        "compliance-filing",
        "launch",
    ]


async def test_initiative_launch_held_when_filing_cleared() -> None:
    orch, guardrails = _initiative(
        _connectors(**{"pricing:cost": "100", "pricing:margin": "0.25", "filing:FT-1": "cleared"})
    )
    result = await orch.run(InitiativeRequest(name="FX-Hedge", filing_token="FT-1"))
    assert result.outputs["pricing"]["price"] == pytest.approx(125.0)
    assert result.outputs["launch"]["blocked"] is False
    assert result.outputs["launch"]["executed"] is False
    assert guardrails.pending()[0].tool_name == "product_launch"


async def test_initiative_launch_blocked_without_filing() -> None:
    orch, guardrails = _initiative(_connectors(**{"pricing:cost": "100", "pricing:margin": "0.25"}))
    result = await orch.run(InitiativeRequest(name="FX-Hedge", filing_token=None))
    assert result.outputs["compliance-filing"]["passed"] is False
    assert result.outputs["launch"]["blocked"] is True
    assert guardrails.pending() == []


async def test_initiative_orders_discovery_pricing_gate_launch() -> None:
    orch, _ = _initiative(
        _connectors(**{"pricing:cost": "100", "pricing:margin": "0.25", "filing:FT-1": "cleared"})
    )
    result = await orch.run(InitiativeRequest(name="FX-Hedge", filing_token="FT-1"))
    assert result.order == ["product-management", "pricing", "compliance-filing", "launch"]


# --- commercial loop (parallel) -------------------------------------------


def test_commercial_graph_is_parallel() -> None:
    orch, _ = _commercial()
    graph = orch.build_graph(CommercialRequest(client_id="C1", kyc_token="KT-1"))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert all(s.depends_on == () for s in graph.steps)
    assert {s.name for s in graph.steps} == {
        "sales-distribution",
        "client-onboarding",
        "client-services",
    }


async def test_commercial_loop_runs_concurrently() -> None:
    barrier = asyncio.Barrier(len(_COMMERCIAL_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _COMMERCIAL_PROMPTS:
            await barrier.wait()  # only releases if all three overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _commercial(transport=gated, connectors=_connectors(**{"kyc:KT-1": "cleared"}))
    result = await asyncio.wait_for(
        orch.run(CommercialRequest(client_id="C1", kyc_token="KT-1")), timeout=1.0
    )
    assert result.outputs["sales-distribution"]["workstream"] == "sales-distribution"


async def test_commercial_onboarding_blocked_without_kyc() -> None:
    orch, guardrails = _commercial()
    result = await orch.run(CommercialRequest(client_id="C1", kyc_token=None))
    assert result.outputs["client-onboarding"]["blocked"] is True
    assert guardrails.pending() == []
