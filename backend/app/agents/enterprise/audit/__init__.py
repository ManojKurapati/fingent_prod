"""Internal Audit & Controls group-agent.

Independent assurance: test controls, evaluate risk, and protect the integrity of
financial processes. Built from the FP&A reference pattern (see
``app/agents/enterprise/fpa/NOTES_FOR_TEMPLATE.md``).

Orchestration is a **sequential macro-flow** (per ``claude1.md`` §7):
``audit-planning -> testing -> findings-reporting -> remediation-tracking``. The
**testing stage fans out** (``control-test:<id>`` ‖ ``sox-controls``), so the
graph is realised as a HYBRID DAG with a strictly-ordered spine. Issuing
(publishing) the audit report is a **consequential** action, gated behind CAE
approval through the guardrail engine (default-deny, human-in-the-loop). This
agent observes (reads other agents' audit traces) but does not act on the ledger,
preserving independence.
"""
