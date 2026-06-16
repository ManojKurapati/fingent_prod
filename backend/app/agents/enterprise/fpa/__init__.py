"""FP&A (Financial Planning & Analysis) group-agent — REFERENCE IMPLEMENTATION.

The forward-looking analytical engine: plan, forecast, and translate financial
data into decision-ready analysis. Built as the copy target every other
group-agent imitates (see ``NOTES_FOR_TEMPLATE.md``).

Orchestration is **hybrid** (per ``claude1.md`` §2): a sequential spine
``data-intake -> budget-consolidation`` feeds a PARALLEL fan-out
(``forecast-engine`` ‖ ``variance:<cost-centre>`` ‖ ``revenue-analytics`` ‖
``scenario-modelling``) that fans in to ``reporting-packs``. Requesting variance
commentary from a cost-centre owner is a **consequential** action and is routed
through the guardrail engine (default-deny, human-in-the-loop).
"""
