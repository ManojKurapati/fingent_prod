"""Investment Banking group-agent.

Originate, structure, and execute capital-raising and strategic-advisory mandates
(M&A, ECM, DCM, leveraged finance, restructuring) end-to-end.

Orchestration is **hybrid** (per ``claude2.md`` §1): origination feeds a mandate,
``modeling-diligence`` must complete before drafting or execution, then
``materials-drafting`` ‖ ``compliance-gate`` fan out from diligence and the
single selected execution subagent (``ma-execution`` | ``ecm-dcm-levfin`` |
``restructuring``) runs only behind a cleared compliance gate. The client-facing
launch is a **consequential** action — denied outright if the compliance gate
fails (conflicts / MNPI wall-crossing) and otherwise held for human approval
(default-deny).
"""
