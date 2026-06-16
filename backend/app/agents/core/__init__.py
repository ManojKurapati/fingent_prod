"""Agent core — FROZEN CONTRACT.

Public interface other sessions import. Do not modify the signatures or shapes of
anything exported here without a coordinated migration (see CONTRACTS.md).
"""

from app.agents.core.gateway import (
    DEFAULT_PRICING,
    MODEL_IDS,
    ClaudeGateway,
    GatewayError,
    LLMResponse,
    ModelTier,
    RawCompletion,
    TierUsage,
    TokenUsage,
)
from app.agents.core.models import (
    EmitFn,
    GraphValidationError,
    OrchestrationMode,
    RunResult,
    Step,
    StepContext,
    StepEvent,
    StepFailedError,
    StepGraph,
    StepRun,
    StepStatus,
    hybrid,
    parallel,
    sequential,
)
from app.agents.core.orchestrator import BaseOrchestrator, Subagent
from app.agents.core.runner import run_graph

__all__ = [  # noqa: RUF022  (grouped by concern, not alphabetised)
    # models
    "OrchestrationMode",
    "StepStatus",
    "StepEvent",
    "StepContext",
    "Step",
    "StepGraph",
    "StepRun",
    "EmitFn",
    "RunResult",
    "GraphValidationError",
    "StepFailedError",
    "sequential",
    "parallel",
    "hybrid",
    # runner
    "run_graph",
    # orchestrator / subagent
    "BaseOrchestrator",
    "Subagent",
    # gateway
    "ClaudeGateway",
    "ModelTier",
    "LLMResponse",
    "RawCompletion",
    "TokenUsage",
    "TierUsage",
    "GatewayError",
    "MODEL_IDS",
    "DEFAULT_PRICING",
]
