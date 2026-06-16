"""Orchestrator-graph tests for Internal Audit & Controls.

The engagement is a **sequential macro-flow** (``audit-planning -> testing ->
findings-reporting -> remediation-tracking``) with a **parallel testing stage**
(``control-test:<id>`` ‖ ``sox-controls``). Because the testing stage fans out,
the graph is built as HYBRID; tests assert both the spine ordering AND that the
testing stage truly overlaps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.agents.core import ClaudeGateway, OrchestrationMode, RawCompletion
from app.agents.enterprise.audit.orchestrator import AuditEngagementOrchestrator
from app.agents.enterprise.audit.schemas import EngagementRequest
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine

# Gateway prompts emitted by the parallel testing stage only.
_TESTING_PROMPTS = {"test control", "assess SOX matrix"}


async def _stub(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=1, output_tokens=1)


def _seeded_connectors() -> ToolRegistry:
    store = FakeStore(
        data={
            "evidence:c1": "fail",  # control deficiency
            "evidence:c2": "pass",
            "sox:c1": "effective",
            "sox:c2": "deficient",  # SOX deficiency
        }
    )
    return build_fake_connector(store=store)


def _orchestrator(
    *,
    transport: Callable[..., Awaitable[RawCompletion]] = _stub,
    connectors: ToolRegistry | None = None,
) -> tuple[AuditEngagementOrchestrator, GuardrailEngine]:
    guardrails = GuardrailEngine(audit=InMemoryAuditLog())
    orch = AuditEngagementOrchestrator(
        gateway=ClaudeGateway(transport=transport),
        guardrails=guardrails,
        connectors=connectors or _seeded_connectors(),
    )
    return orch, guardrails


def _request() -> EngagementRequest:
    return EngagementRequest(engagement="FY26-rev", controls=["c1", "c2"])


def test_graph_is_hybrid_sequential_spine_with_parallel_testing() -> None:
    orch, _ = _orchestrator()
    graph = orch.build_graph(_request())
    assert graph.mode is OrchestrationMode.HYBRID

    by_name = {s.name: s for s in graph.steps}
    assert by_name["audit-planning"].depends_on == ()
    # parallel testing stage gates on planning, members mutually independent
    assert by_name["control-test:c1"].depends_on == ("audit-planning",)
    assert by_name["control-test:c2"].depends_on == ("audit-planning",)
    assert by_name["sox-controls"].depends_on == ("audit-planning",)
    # findings fans in over the whole testing stage
    assert set(by_name["findings-reporting"].depends_on) == {
        "control-test:c1",
        "control-test:c2",
        "sox-controls",
    }
    # remediation strictly follows findings
    assert by_name["remediation-tracking"].depends_on == ("findings-reporting",)


async def test_testing_stage_runs_concurrently() -> None:
    """control-test:c1 ‖ control-test:c2 ‖ sox-controls must overlap."""
    barrier = asyncio.Barrier(len(["c1", "c2"]) + 1)  # 2 control tests + sox

    async def gated(model: str, prompt: str, **_: object) -> RawCompletion:
        if prompt in _TESTING_PROMPTS:
            await barrier.wait()  # only releases if all testing steps overlap
        return RawCompletion(text="ok", input_tokens=1, output_tokens=1)

    orch, _ = _orchestrator(transport=gated)
    result = await asyncio.wait_for(orch.run(_request()), timeout=1.0)
    assert result.outputs["remediation-tracking"]["open"] >= 1


async def test_spine_ordering_holds() -> None:
    orch, _ = _orchestrator()
    result = await orch.run(_request())
    pos = {name: i for i, name in enumerate(result.order)}
    assert pos["audit-planning"] < pos["control-test:c1"]
    assert pos["audit-planning"] < pos["sox-controls"]
    assert pos["control-test:c1"] < pos["findings-reporting"]
    assert pos["sox-controls"] < pos["findings-reporting"]
    assert pos["findings-reporting"] < pos["remediation-tracking"]
    assert result.order[-1] == "remediation-tracking"


async def test_engagement_holds_report_publish_for_cae_approval() -> None:
    orch, guardrails = _orchestrator()
    result = await orch.run(_request())

    findings = result.outputs["findings-reporting"]
    assert findings["control_failures"] == ["c1"]
    assert findings["sox_deficiencies"] == ["c2"]
    assert sorted(findings["findings"]) == ["c1", "c2"]
    # default-deny: report issuance held for the CAE
    pending = guardrails.pending()
    assert len(pending) == 1
    assert pending[0].tool_name == "audit_publish_findings"

    outcome = await guardrails.approve(pending[0].id, approver="cae-jo")
    assert outcome.executed is True
