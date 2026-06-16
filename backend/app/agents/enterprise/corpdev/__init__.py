"""Corporate Development & Strategy group-agent.

Drives inorganic growth, evaluates transactions, and shapes the investor story.

Orchestration is **hybrid** (per ``claude1.md`` §8): a sequential deal spine
``pipeline-sourcing -> (valuation-modelling ‖ due-diligence) -> deal-materials``
(valuation and diligence iterate in parallel), plus two independent standing lanes
``strategy-analysis`` ‖ ``investor-relations`` that run on their own cadence as a
PARALLEL standalone path. Publishing a deal recommendation (board gate) and any
external investor communication (Reg FD-style) are **consequential** actions routed
through the guardrail engine (default-deny).
"""
