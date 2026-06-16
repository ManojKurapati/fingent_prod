"""Product, Strategy & Client group-agent — financial-services §12.

Defines financial products, sets pricing, and owns the commercial relationship.
Orchestration is **hybrid** (per ``claude2.md`` §12): product definition is
sequential at the front — ``product-management`` (discovery) -> ``pricing``
(economics) -> a mandatory **compliance/regulatory-filing gate** before the
consequential ``launch``. Post-launch the commercial loop runs in PARALLEL
(``sales-distribution`` ‖ ``client-onboarding`` ‖ ``client-services``), with
onboarding internally gated by KYC before client activation. Launch and client
activation are both consequential and routed through the guardrail engine
(default-deny, human-in-the-loop).
"""
