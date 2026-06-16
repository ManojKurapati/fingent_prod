"""Asset & Investment Management group-agent.

Research, allocate, and manage portfolios to deliver mandate-compliant,
risk-adjusted returns.

Orchestration is **hybrid** (per ``claude2.md`` §3): a sequential
``macro-strategy -> asset-allocation`` spine runs alongside a PARALLEL
``research:<name>`` fan-out; both join at ``portfolio-construction``; orders then
pass a MANDATORY ``mandate-risk-gate`` (limits / liquidity / suitability) before
``buyside-execution``. Placing orders is a **consequential** action — denied
outright on a gate fail and otherwise held for PM approval (default-deny). A
standalone PARALLEL research path is exposed separately.
"""
