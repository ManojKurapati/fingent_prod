"""Shared application context — FROZEN CONTRACT.

Bundles the platform's shared services (audit log, guardrail engine, job queue,
Claude gateway, connector registry) into one object that group-agents receive via
FastAPI dependency injection. Agents never construct these themselves — they ask
for the context.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.agents.core import ClaudeGateway, RawCompletion
from app.audit import InMemoryAuditLog
from app.connectors import ToolRegistry, build_fake_connector
from app.guardrails import GuardrailEngine
from app.jobs import InMemoryJobQueue


async def _stub_transport(model: str, prompt: str, **_: object) -> RawCompletion:
    """A no-network transport so the app boots without API keys.

    Production wires a transport backed by the Anthropic SDK; this echoes the
    prompt and reports nominal token counts for local/dev/test runs.
    """
    return RawCompletion(
        text=f"[{model}] {prompt}",
        input_tokens=max(1, len(prompt) // 4),
        output_tokens=8,
    )


@dataclass
class AppContext:
    """The shared services every agent and platform endpoint depends on."""

    audit: InMemoryAuditLog
    guardrails: GuardrailEngine
    jobs: InMemoryJobQueue
    gateway: ClaudeGateway
    connectors: ToolRegistry


def build_context() -> AppContext:
    """Construct the default in-process context (fakes for local/dev/test)."""
    audit = InMemoryAuditLog()
    return AppContext(
        audit=audit,
        guardrails=GuardrailEngine(audit=audit),
        jobs=InMemoryJobQueue(),
        gateway=ClaudeGateway(transport=_stub_transport),
        connectors=build_fake_connector(),
    )


def get_context(request: Request) -> AppContext:
    """FastAPI dependency: the context stored on app startup."""
    context: AppContext = request.app.state.context
    return context
