"""Finance Systems & Operations group-agent.

Run the finance platforms, govern financial data, and continuously improve how
finance operates. Built from the FP&A reference pattern (see
``app/agents/enterprise/fpa/NOTES_FOR_TEMPLATE.md``).

Orchestration is **hybrid** (per ``claude1.md`` §9): a sequential spine
``data-pipelines -> dashboards-reporting`` (clean, reconciled data must land before
it is rendered) plus three independent parallel lanes (``erp-administration`` ‖
``process-transformation`` ‖ ``o2c-p2p-process-owner``). Applying an ERP access /
config change that introduces a segregation-of-duties conflict is a
**consequential** action, gated through the guardrail engine (default-deny; the
approval feeds Internal Audit).
"""
