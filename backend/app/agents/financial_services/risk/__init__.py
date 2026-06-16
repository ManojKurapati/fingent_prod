"""Risk Management group-agent.

Identifies, measures, and governs financial and non-financial risk to keep
enterprise exposure within board-approved appetite (per ``claude2.md`` §8).

Orchestration is a **hybrid** parallel fan-out into a sequential aggregation tail:
``market-risk`` ‖ ``credit-risk`` ‖ ``operational-risk`` ‖ ``liquidity-risk`` ‖
``model-validation`` compute concurrently against one snapshot, then
``erm-aggregation`` is the barrier that consolidates and tests against appetite —
escalating any breach to the CRO through a default-deny guardrail.

This agent also **publishes the synchronous risk gates** (``pre_trade_gate`` /
``limit_check_gate``) every other agent must clear before committing capital. The
gates are fail-closed: a missing limit denies.
"""
