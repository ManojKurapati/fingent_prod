"""Global guardrail audit (wave 4, task 2).

Asserts the platform-wide invariant: every tool flagged ``consequential = True`` is
unreachable without an approval record (default-deny), and no agent code bypasses
the guardrail by calling such a tool's ``invoke`` directly.
"""

from __future__ import annotations

import pytest
from app.audit import InMemoryAuditLog
from app.guardrails import ApprovalState, GuardrailEngine
from app.integration.tool_audit import (
    consequential_tool_classes,
    find_consequential_bypasses,
    scan_source_for_bypasses,
)


def test_discovery_finds_the_consequential_action_tools() -> None:
    classes = consequential_tool_classes()
    names = {c.__name__ for c in classes}
    assert classes, "no consequential tools discovered — discovery is broken"
    # A representative spread across enterprise + financial-services groups.
    assert {
        "PublishBoardPackTool",
        "ExecutePaymentTool",
        "RouteOrderTool",
        "SettlementInstructionTool",
        "FundLoanTool",
        "BindPolicyTool",
    } <= names
    assert all(getattr(c, "consequential", False) for c in classes)


@pytest.mark.parametrize("tool_cls", consequential_tool_classes(), ids=lambda c: c.__name__)
async def test_every_consequential_tool_is_default_denied(tool_cls: type) -> None:
    audit = InMemoryAuditLog()
    engine = GuardrailEngine(audit=audit)
    tool = tool_cls()
    assert tool.consequential is True

    outcome = await engine.submit(tool, {}, actor="agent", approver_role="approver")

    # Held, not executed; an approval record exists and is pending.
    assert outcome.executed is False
    assert outcome.request is not None
    assert engine.get(outcome.request.id).state is ApprovalState.PENDING

    events = await audit.events()
    assert any(e.action == "approval.requested" for e in events)
    # Nothing was granted or executed before approval.
    assert not any(e.action == "approval.granted" for e in events)
    assert not any(e.action == "tool_call" and e.payload.get("gated") for e in events)

    # The action only becomes reachable once a human approves it.
    granted = await engine.approve(outcome.request.id, approver="human")
    assert granted.executed is True


def test_no_agent_code_bypasses_the_guardrail() -> None:
    assert find_consequential_bypasses() == []


def test_bypass_scanner_detects_a_direct_invoke() -> None:
    """The detector must actually flag a bypass (so an empty result is meaningful)."""
    source = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self._tool = RouteOrderTool()\n"
        "    async def go(self, p):\n"
        "        return await self._tool.invoke(p)\n"  # <-- bypass
    )
    violations = scan_source_for_bypasses(
        source, filename="bad.py", consequential_names={"RouteOrderTool"}
    )
    assert len(violations) == 1
    assert "RouteOrderTool" in violations[0]


def test_bypass_scanner_allows_inline_and_variable_bypass_and_passes_submit() -> None:
    inline = "x = SettlementInstructionTool().invoke(p)\n"
    assert scan_source_for_bypasses(
        inline, filename="i.py", consequential_names={"SettlementInstructionTool"}
    )
    # Handing the tool to submit() is NOT a bypass.
    ok = (
        "tool = SettlementInstructionTool()\n"
        "await guardrails.submit(tool, payload, actor='a', approver_role='r')\n"
    )
    assert (
        scan_source_for_bypasses(
            ok, filename="ok.py", consequential_names={"SettlementInstructionTool"}
        )
        == []
    )
