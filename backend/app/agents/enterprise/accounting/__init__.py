"""Accounting & Controllership group-agent.

Custodian of the ledger: records every transaction accurately and owns the close
and consolidated statements. Orchestration is **hybrid** (per ``claude1.md`` §3):
``close-orchestration`` opens the period, then a PARALLEL sub-ledger fan-out
(``journal-entries`` ‖ ``fixed-assets`` ‖ ``cost-inventory`` ‖
``technical-accounting``) fans in to ``reconciliations``, and ``consolidations``
is sequenced strictly last (all entity books must close first). Posting journal
entries to the GL is a **consequential** action routed through the guardrail
engine (default-deny, human-in-the-loop — Controller sign-off).
"""
