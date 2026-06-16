"""Orchestrator-graph tests for Operations (Middle & Back Office).

The processing pipeline is HYBRID: a strict sequential spine
``trade-support -> settlements`` (you cannot settle an unconfirmed trade), then a
PARALLEL reconciliation layer (``reconciliations`` ‖ ``fund-accounting`` ‖
``custody-ops`` ‖ ``collateral-mgmt``) over the settled records. The standalone
reconciliation run is PARALLEL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.financial_services.operations_middle_back_office.orchestrator import (
    OpsPipelineOrchestrator,
    OpsReconOrchestrator,
)
from app.agents.financial_services.operations_middle_back_office.schemas import (
    OpsReconRequest,
    TradeProcessRequest,
)
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

_RECON_PROMPTS = {"reconcile books", "compute nav", "reconcile custody", "manage collateral"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded(affirmed: bool = True) -> ToolRegistry:
    data = {
        "recon:internal": "100",
        "recon:external": "100",
        "nav:assets": "1000",
        "nav:liabilities": "200",
        "nav:shares": "100",
        "custody:holdings": "500",
        "custody:custodian": "500",
        "collateral:exposure": "300",
        "collateral:posted": "120",
    }
    if affirmed:
        data["trade:T1:affirmed"] = "yes"
    return build_fake_connector(store=FakeStore(data=data))


def _pipeline(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[OpsPipelineOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = OpsPipelineOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded(),
    )
    return orch, guardrails


def _req(trade_id: str = "T1") -> TradeProcessRequest:
    return TradeProcessRequest(trade_id=trade_id, amount=1_000.0)


def test_pipeline_graph_is_hybrid_spine_then_parallel_recon() -> None:
    orch, _ = _pipeline()
    graph = orch.build_graph(_req())
    assert graph.mode is OrchestrationMode.HYBRID
    by_name = {s.name: s for s in graph.steps}
    # sequential spine: confirm before settle
    assert by_name["trade-support"].depends_on == ()
    assert by_name["settlements"].depends_on == ("trade-support",)
    # parallel reconciliation layer, each gated only on settlement
    for surface in ("reconciliations", "fund-accounting", "custody-ops", "collateral-mgmt"):
        assert by_name[surface].depends_on == ("settlements",)


async def test_recon_layer_runs_concurrently() -> None:
    barrier = asyncio.Barrier(len(_RECON_PROMPTS))

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _RECON_PROMPTS:
            await barrier.wait()  # only releases if all four overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _pipeline(transport=gated)
    result = await asyncio.wait_for(orch.run(_req()), timeout=1.0)
    assert result.outputs["fund-accounting"]["nav"] == pytest.approx(8.0)


async def test_pipeline_spine_orders_confirm_before_settle_before_recon() -> None:
    orch, _ = _pipeline()
    result = await orch.run(_req())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["trade-support"] < pos["settlements"]
    assert pos["settlements"] < pos["reconciliations"]
    assert pos["settlements"] < pos["collateral-mgmt"]


async def test_confirmed_trade_holds_settlement_for_approval() -> None:
    orch, guardrails = _pipeline()
    result = await orch.run(_req())
    settlement = result.outputs["settlements"]
    assert settlement["blocked"] is False
    assert settlement["executed"] is False
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "ops_instruct_settlement"


async def test_unconfirmed_trade_blocks_settlement_entirely() -> None:
    orch, guardrails = _pipeline(connectors=_seeded(affirmed=False))
    result = await orch.run(_req())
    settlement = result.outputs["settlements"]
    assert settlement["blocked"] is True
    assert settlement["executed"] is False
    assert guardrails.pending() == []  # nothing is even submitted


# --- standalone reconciliation run (parallel) -----------------------------


def test_recon_graph_is_parallel() -> None:
    orch = OpsReconOrchestrator(gateway=ClaudeGateway(transport=_stub), connectors=_seeded())
    graph = orch.build_graph(OpsReconRequest(as_of="2026-06-16"))
    assert graph.mode is OrchestrationMode.PARALLEL
    assert all(s.depends_on == () for s in graph.steps)
    assert {s.name for s in graph.steps} == {
        "reconciliations",
        "fund-accounting",
        "custody-ops",
        "collateral-mgmt",
    }


async def test_recon_run_produces_all_surfaces() -> None:
    orch = OpsReconOrchestrator(gateway=ClaudeGateway(transport=_stub), connectors=_seeded())
    result = await orch.run(OpsReconRequest(as_of="2026-06-16"))
    assert result.outputs["custody-ops"]["reconciled"] is True
    assert result.outputs["collateral-mgmt"]["margin_call"] == pytest.approx(180.0)
