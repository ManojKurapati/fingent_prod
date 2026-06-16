"""Compliance, Legal & Financial Crime group-agent.

Keeps the firm within legal and regulatory bounds and defends it against money
laundering, fraud, and sanctions exposure (per ``claude2.md`` §9).

This agent is the firm's **gate-of-record**. Onboarding screening runs ``aml-kyc``
‖ ``sanctions-screening`` in parallel, then a sequential ``fraud-investigation``
disposition: any hit blocks clearance and recommends a SAR. Filing a SAR is a
**consequential** external filing, routed through the guardrail engine
(default-deny). ``compliance-monitoring`` ‖ ``regulatory-affairs`` ‖
``legal-counsel`` run as a PARALLEL continuous loop. The agent also **publishes the
synchronous compliance gate** (``compliance_gate`` -> PASS/HOLD/DENY) every other
agent must clear before client-facing, market, or filing actions — fail-closed.
"""
