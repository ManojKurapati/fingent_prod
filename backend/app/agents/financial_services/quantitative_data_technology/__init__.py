"""Quantitative, Data & Technology group-agent — financial-services §11.

Builds the models, research, and systematic strategies behind pricing, risk, and
trading. Orchestration is **parallel by default** (per ``claude2.md`` §11): the
six workstreams (``quant-pricing`` ‖ ``quant-research`` ‖ ``risk-model-dev`` ‖
``data-science`` ‖ ``financial-engineering`` ‖ ``systematic-dev``) fan out
independently. The non-negotiable sequential dependency is promotion to
production: a candidate must clear an **independent model-validation gate** (the
Risk Agent's validation token) before it is deployed. Promotion is a
**consequential** action routed through the guardrail engine (default-deny).
"""
