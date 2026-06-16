"""Wealth Management & Private Banking group-agent (claude2.md §5).

Advise individuals and families on growing, protecting, and transferring wealth,
and deliver bespoke banking and discretionary portfolio management.

Orchestration is **hybrid, suitability-gated** (per ``claude2.md`` §5).
``client-onboarding-kyc`` is the sequential entry gate — no advice runs before KYC
clears; then ``financial-planning`` ‖ ``investment-advice`` run in PARALLEL and fan
in to ``plan-reconciliation``. The two consequential actions — a discretionary
rebalance (``discretionary-pm``) and a Lombard credit facility (``private-banking``)
— each run as a short SEQUENTIAL chain whose suitability/credit gate must PASS, then
the asset move / credit extension is held by the guardrail engine (default-deny)
until a human signs off.
"""
