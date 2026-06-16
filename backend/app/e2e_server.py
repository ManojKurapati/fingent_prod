"""End-to-end test server.

A real FastAPI app (the same ``create_app`` the product uses) wired with:

* an **auto-draining** in-memory job queue, so an enqueued agent run executes
  inline — a single-process stand-in for the worker fleet, sufficient to drive the
  UI end to end without Redis/arq;
* connectors **seeded** so the demo flows reach a decision: an FP&A cost centre
  breaches its variance threshold (-> commentary approval), and a trading order
  clears the pre-trade risk gate (-> routing approval).

This entrypoint is for Playwright e2e only (``uvicorn app.e2e_server:app``); it is
never imported by the product app or unit tests, so it is excluded from coverage.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import ClaudeGateway, RawCompletion
from app.api.context import AppContext
from app.audit import InMemoryAuditLog
from app.connectors import FakeStore, build_fake_connector
from app.guardrails import GuardrailEngine
from app.jobs import InMemoryJobQueue, Job
from app.main import create_app


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    return RawCompletion(text="ok", input_tokens=4, output_tokens=2)


class AutoDrainJobQueue(InMemoryJobQueue):
    """Runs each job to completion as soon as it is enqueued (inline worker)."""

    async def enqueue(self, *args: Any, **kwargs: Any) -> Job:
        job = await super().enqueue(*args, **kwargs)
        await self.drain()
        return job


def _seeded_store() -> FakeStore:
    return FakeStore(
        data={
            # FP&A: cc1 actual far above plan -> variance breach -> commentary request.
            "actual:cc1": "130",
            "plan:cc1": "100",
            "actual:cc2": "100",
            "plan:cc2": "100",
            # Sales & Trading: order clears the pre-trade risk gate -> routing approval.
            "price:AAPL": "100",
            "limit:eqbook": "1000000",
            "exposure:eqbook": "0",
            "suitable:acct1": "yes",
        }
    )


def build_e2e_context() -> AppContext:
    audit = InMemoryAuditLog()
    return AppContext(
        audit=audit,
        guardrails=GuardrailEngine(audit=audit),
        jobs=AutoDrainJobQueue(),
        gateway=ClaudeGateway(transport=_stub_transport),
        connectors=build_fake_connector(store=_seeded_store()),
    )


app = create_app(build_e2e_context())
