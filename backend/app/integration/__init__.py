"""Cross-cutting integration layer (wave 4).

Composes the merged group-agents into multi-agent chains, audits the global
guardrail invariant, and provides bounded/idempotent fan-out for load-bearing
parallel work. Imports only from the frozen platform contracts.
"""

from app.integration.chain import ChainResult, ChainStep, run_chain
from app.integration.chains import build_cfo_enterprise_chain, build_fs_trade_chain

__all__ = [
    "ChainResult",
    "ChainStep",
    "build_cfo_enterprise_chain",
    "build_fs_trade_chain",
    "run_chain",
]
