"""Insurance group-agent.

Prices, underwrites, and manages risk transfer across the insurance lifecycle, from
policy inception to claim settlement (per ``claude2.md`` §7).

Orchestration is **hybrid**: a parallel pricing fan-out (``actuarial`` ‖
``cat-modelling``) joins at ``underwriting``, which decides against a
**risk-appetite / accumulation gate**. Binding a policy is a **consequential**
action: it must clear the mandatory accumulation gate AND a default-deny guardrail
approval before any risk is bound. ``reinsurance`` ‖ ``product`` run as a
portfolio-level PARALLEL optimisation; ``claims`` is the post-bind lifecycle path.
"""
