"""Private Markets group-agent (claude2.md §4).

Source, underwrite, and steward illiquid equity, credit, and real-asset
investments across their full lifecycle.

Orchestration is **hybrid** (per ``claude2.md`` §4): ``origination-pipeline``
qualifies a deal, three diligence workstreams fan out in PARALLEL, exactly one
asset-class underwriting subagent fans them in to an IC memo, and ``ic-commitment``
routes the **consequential** capital commitment through the guardrail engine — the
mandatory **Investment Committee approval gate** (default-deny, human-in-the-loop).
No capital is committed before the IC votes. Post-close, ``portfolio-stewardship``
runs as a standalone sequential monitor.
"""
