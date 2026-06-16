"""Agent module template — THE pattern wave 2/3 sessions copy.

This package is a complete, working, tested group-agent. It is named ``_template``
so :mod:`app.agents.discovery` skips it (templates do not ship routes). To build a
real group-agent, copy this directory to::

    app/agents/enterprise/<group>/            # enterprise finance
    app/agents/financial_services/<group>/    # financial services

and replace ``template`` everywhere with your group name.

File layout (every group-agent mirrors this)::

    <group>/
      __init__.py        # package docstring
      schemas.py         # typed RunRequest / response models
      subagents.py       # one Subagent per responsibility cluster
      orchestrator.py    # BaseOrchestrator subclass; build_graph() per the spec
      service.py         # job handler + register() wiring orchestrator -> jobs/SSE
      router.py          # APIRouter exposing `router`; auto-discovered

Test layout (mirror under ``tests/agents/<area>/<group>/``)::

    test_orchestrator.py   # assert the graph shape + concurrency/ordering
    test_subagents.py      # each subagent with mocked gateway + fake connectors
    test_router.py         # httpx: enqueue -> drain -> status; guardrail blocks

Rules:
* Follow STRICT TDD — failing test first, minimal code to green, refactor.
* Honour the orchestration choice (sequential/parallel/hybrid) your spec documents
  and ASSERT it in tests.
* Route EVERY consequential action through the guardrail engine. Add a test that
  proves it is blocked (default-deny) without approval.
* Import shared contracts from ``app.agents.core``, ``app.connectors``,
  ``app.jobs``, ``app.guardrails``, ``app.audit``, ``app.api.context`` — never edit
  them. If you think you need a core change, STOP and report.
"""
