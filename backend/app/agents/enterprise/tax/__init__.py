"""Tax group-agent.

Manage tax obligations, optimise the group's effective tax rate, and ensure
compliance across jurisdictions (claude1.md §6). Orchestration is **hybrid**: a
parallel fan-out by tax type (``direct-tax-compliance`` ‖ ``indirect-tax`` ‖
``transfer-pricing`` ‖ ``international-tax``) plus a standing ``audit-defence``
stream, fanning in to ``tax-provision`` (current/deferred -> ETR + disclosures).
Filing a return externally is a **consequential** action routed through the
guardrail engine (default-deny, human-in-the-loop) on a sequential filing path.
"""
