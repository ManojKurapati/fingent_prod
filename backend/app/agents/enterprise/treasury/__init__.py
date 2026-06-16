"""Treasury group-agent.

Guardian of cash, liquidity, and financial risk. ``claude1.md`` §5 documents
Treasury as a **sequential dependency chain** — you cannot forecast liquidity
without the cash position, nor decide hedging / covenant headroom without the
forecast — with a **parallel tail** (``fx-hedging`` ‖ ``debt-covenants``) and
``bank-connectivity`` as an independent standing service.

Because a strictly-linear SEQUENTIAL graph cannot express a parallel tail, the
realised :class:`TreasuryDailyPositionOrchestrator` graph mode is HYBRID; the
sequential spine ordering and the concurrent tail are both asserted in tests, so
the documented flow is honoured exactly. The terminal cash-movement actions
(``hedge/execute``, ``sweep``) are **consequential** and routed through the
guardrail engine (default-deny, Treasurer sign-off) via dedicated endpoints.
"""
