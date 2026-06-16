"""Retail & Commercial Banking group-agent (claude2.md §6).

Serve individuals and businesses with deposits, lending, and credit at scale while
controlling risk on every facility.

Orchestration is **sequential** (lending is a strict pipeline, per ``claude2.md``
§6): an intake channel (``personal-banking`` | ``commercial-rm`` | ``branch-ops``)
→ ``loan-origination`` (docs, pre-qual) → ``credit-analysis`` (rating, limit) →
``underwriting`` (verify, DSR/LTV, decision against credit policy) → ``loan-funding``.
Funding is the **consequential** lend: it is routed through the guardrail engine
(default-deny) and only proposed when underwriting approves within risk appetite —
so a declined application disburses nothing.
"""
