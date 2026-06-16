"""Sales & Trading / Markets group-agent.

Price, quote, distribute, and execute trades across asset classes while
continuously managing desk risk and client flow.

Orchestration is **hybrid with a hard sequential gate** (per ``claude2.md`` §2):
``sales-coverage`` ‖ ``pricing-quoting`` ‖ ``quant-signals`` ‖ ``structuring``
stream in parallel and fan in to the MANDATORY ``pre-trade-risk-gate`` (limits /
inventory / suitability). Only on PASS does ``execution-algo`` route the order —
a **consequential** action denied outright on a gate fail and otherwise held for
trader/risk approval (default-deny). ``risk-hedging`` re-hedges post-fill.
"""
