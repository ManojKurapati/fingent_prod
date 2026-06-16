# NOTES_FOR_TEMPLATE — FP&A reference implementation

What wave 2/3 sessions should copy from `app/agents/enterprise/fpa/` (the proven
pattern that extends `app/agents/_template/`):

1. **File layout per group:** `schemas.py` (pydantic `*Request` + `RunAccepted`),
   `subagents.py` (one `Subagent` per responsibility), `orchestrator.py`
   (`BaseOrchestrator` subclass, `build_graph` honouring the spec's mode),
   `service.py` (job handler(s) + `register(ctx)`), `router.py` (module-level
   `router`). Tests mirror under `tests/agents/<area>/<group>/`.
2. **Honour the documented orchestration & ASSERT it.** FP&A is HYBRID: build the
   graph with `hybrid([...])`, then test (a) the exact `depends_on` shape, (b) that
   the fan-out truly overlaps using an `asyncio.Barrier` in the fake transport
   (deadlocks unless concurrent), and (c) spine ordering via `RunResult.order`.
   A second `SEQUENTIAL` orchestrator (`FpaScenarioOrchestrator`) shows a standalone
   path — use `sequential([...])` and assert the step order.
3. **Deterministic maths via fake connectors, narrative via the gateway.** Pull
   numeric inputs from `ToolRegistry` (`kv_read`) so tests seed a `FakeStore`; use
   `ClaudeGateway` (mocked transport) only for validation/narrative. Pass
   `connectors` into the orchestrator from `AppContext`.
4. **Route EVERY consequential action through guardrails (default-deny).** FP&A
   gates the variance-commentary "ping the owner" tool (`consequential = True`) via
   `guardrails.submit(...)`; it is held, never executed, until approved. Tests
   prove `pending()` holds it and that approval flips `executed` to `True`.
5. **Endpoints enqueue, workers run.** `router.py` validates intake, calls
   `register(ctx)` (idempotent), enqueues with an `idempotency_key`, and returns a
   `job_id`. Progress flows over the shared `GET /jobs/{id}/events` SSE; the handler
   forwards each `StepEvent` as a `step` `ProgressEvent`.
6. **Auto-discovery, no shared edits.** Exposing `router` is all it takes — do NOT
   edit `main.py`/registries. Tests mount via `create_app(context)` alone.
7. **Frontend page** lives in `frontend/src/pages/<group>/`: reuse `JobTimeline`
   (live grid that greens as steps complete), `ApprovalDrawer` (human-in-the-loop),
   and the frozen `lib/` clients; put group-specific POSTs in a local `api.ts`.
   Make the `EventSource` injectable so the live grid is testable (msw + a fake
   EventSource). NOTE: the page is exported but not yet mounted — integration wires
   it into `App.tsx` (one import + route) to avoid parallel sessions colliding on a
   shared file.
8. **DoD gate:** `make check` (ruff + ruff format + mypy + pytest cov≥85) and
   `npm run cov && npm run typecheck && npm run lint`. FP&A ships at 100% backend
   coverage on new code.
