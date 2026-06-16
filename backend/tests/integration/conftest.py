"""Shared fixtures for cross-agent integration tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.agents.core import ClaudeGateway, RawCompletion
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine
from app.observability import Tracer


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    """A deterministic no-network transport with non-zero token counts."""
    return RawCompletion(text="ok", input_tokens=4, output_tokens=2)


@pytest.fixture
def gateway() -> ClaudeGateway:
    return ClaudeGateway(transport=_stub_transport)


@pytest.fixture
def audit() -> InMemoryAuditLog:
    return InMemoryAuditLog()


@pytest.fixture
def guardrails(audit: InMemoryAuditLog) -> GuardrailEngine:
    return GuardrailEngine(audit=audit)


@pytest.fixture
def step_clock() -> Callable[[], float]:
    """A monotonic fake clock so span latencies are positive and deterministic."""
    counter = {"t": 0.0}

    def _clock() -> float:
        counter["t"] += 1.0
        return counter["t"]

    return _clock


@pytest.fixture
def tracer(step_clock: Callable[[], float]) -> Tracer:
    return Tracer(clock=step_clock)


@pytest.fixture
def seeded_connectors() -> ToolRegistry:
    """Connector store seeded so the FS chain's risk/compliance gates all PASS."""
    store = FakeStore(
        data={
            # portfolio (asset-investment-management) mandate-risk-gate
            "target:AAA": "100",
            "target:BBB": "50",
            "limit:PORT-1": "1000000",
            "liquidity:PORT-1": "ok",
            # trading (sales-trading-markets) pre-trade-risk-gate
            "price:AAA": "10",
            "limit:DESK-1": "1000000",
            "exposure:DESK-1": "0",
            "suitable:ACC-1": "yes",
            # operations trade-support confirmation
            "trade:ord-PORT-1:affirmed": "yes",
        }
    )
    return build_fake_connector(store=store)
