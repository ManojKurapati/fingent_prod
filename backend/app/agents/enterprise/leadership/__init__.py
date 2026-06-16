"""Leadership (CFO) group-agent.

The synthesiser at the top of the enterprise finance org: consolidates divisional
outputs, sets capital strategy, and assembles board-ready decisions and guidance.

Orchestration is **hybrid** (per ``claude1.md`` §1): a sequential spine
``divisional-rollup -> capital-strategy`` feeds a parallel fan-out of the
independent standing lanes (``capital-strategy`` ‖ ``budget-plan-signoff`` ‖
``transformation-sponsor``, all gating only on the consolidation), with
``board-investor-reporting`` a partial fan-in that needs the consolidated position
and the capital decision. Publishing the board pack is a **consequential** external
communication and is routed through the guardrail engine (default-deny, CFO gate).
"""
