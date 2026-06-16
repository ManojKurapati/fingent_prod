"""Transactional / Operational Finance group-agent.

The high-volume engine room (claude1.md §4): payables, receivables, billing,
collections, payroll, and procurement. Orchestration is **parallel with one local
sequence** — AP ‖ payroll ‖ procurement ‖ (billing -> accounts-receivable ->
collections) — modelled as a HYBRID DAG. Any cash movement (an AP payment run or a
payroll disbursement) is a **consequential** action routed through the guardrail
engine (default-deny, human-in-the-loop). A standalone AP payment run fans out a
pure PARALLEL per-vendor 3-way match.
"""
