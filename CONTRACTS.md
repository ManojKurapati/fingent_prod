# CONTRACTS — Frozen Interfaces (Wave 0 Foundation)

These are the interfaces wave 2/3 sessions **import and MUST NOT modify**. Treat
every symbol below as frozen: change a signature or shape only in a foundation /
integration session with a coordinated migration. Feature sessions that think they
need a core change **STOP and report** instead of editing.

The rule of thumb: import from `app.agents.core`, `app.connectors`, `app.jobs`,
`app.guardrails`, `app.audit`, `app.api.context`, and `app.agents.discovery`.
Never edit those modules.

---

## Backend (`backend/app`)

### Agent core — `app.agents.core`

```python
# Orchestration shapes
OrchestrationMode.SEQUENTIAL | PARALLEL | HYBRID
StepStatus.QUEUED | RUNNING | COMPLETED | FAILED

# Step graph
@dataclass(frozen) Step(name: str, run: StepRun, depends_on: tuple[str, ...] = ())
@dataclass(frozen) StepGraph(mode, steps)          # validates structure + mode
@dataclass(frozen) StepEvent(step, status, detail) # lifecycle event (SSE/audit)
@dataclass(frozen) StepContext(step, results, emit)# results = dependency outputs
@dataclass        RunResult(outputs, order, events)

sequential(steps) -> StepGraph     # auto-wires a linear chain
parallel(steps)   -> StepGraph     # independent, no deps
hybrid(steps)     -> StepGraph     # arbitrary validated DAG

GraphValidationError, StepFailedError(step, cause)

# Runner (deterministic; independent steps run concurrently)
async run_graph(graph, *, emit=None) -> RunResult

# Subagent + orchestrator base classes
class Subagent[I, O](ABC):
    name: str
    async def execute(self, ctx: StepContext) -> O: ...
    def as_step(self, *, depends_on=()) -> Step

class BaseOrchestrator[R](ABC):
    group: str
    mode: OrchestrationMode
    def build_graph(self, request: R) -> StepGraph: ...
    async def run(self, request, *, emit=None) -> RunResult

# Claude gateway (model routing / retries / token accounting)
ModelTier.OPUS | HAIKU                       # -> claude-opus-4-8 / claude-haiku-4-5-*
@dataclass(frozen) RawCompletion(text, input_tokens, output_tokens)   # transport return
@dataclass(frozen) LLMResponse(text, tier, model, input_tokens, output_tokens)
@dataclass TokenUsage / TierUsage            # accumulated accounting
GatewayError
class ClaudeGateway(transport, *, max_retries=3, base_delay=.05, sleep=None, pricing=None):
    usage -> TokenUsage
    async complete(self, *, prompt, tier=ModelTier.HAIKU, **kwargs) -> LLMResponse
```

Agents **never call a model SDK directly** — always through `ClaudeGateway`.

### Connectors — `app.connectors`

```python
class Tool[I, O](ABC):
    name: str
    consequential: bool = False              # True => MUST be gated by guardrails
    async def invoke(self, payload: I) -> O

class ToolRegistry:
    register(tool) -> tool                   # unique names
    get(name) -> Tool                        # raises ToolNotFoundError
    all() -> list[Tool]
    consequential() -> list[Tool]
    __iter__, __len__

ToolNotFoundError
FakeStore, build_fake_connector(*, store=None) -> ToolRegistry   # tests only
```

### Jobs — `app.jobs`

```python
JobStatus.QUEUED | RUNNING | COMPLETED | FAILED
@dataclass Job(id, kind, payload, status, idempotency_key, max_attempts,
               attempts, result, error, correlation_id)
Emit        = Callable[[ProgressEvent], Awaitable[None]]
JobHandler  = Callable[[Job, Emit], Awaitable[Any]]

class JobQueue(ABC):                          # implement to back with arq/Redis
    register(kind, handler) -> None
    async enqueue(kind, payload, *, idempotency_key=None, max_attempts=3,
                  correlation_id=None) -> Job  # idempotent on key; no double-exec
    get(job_id) -> Job
    async drain() -> None

class InMemoryJobQueue(JobQueue):             # test/dev fake; has `.progress`

# Progress / SSE
@dataclass(frozen) ProgressEvent(job_id, type, payload)
class ProgressBus: async publish / async close / history(job_id) / async subscribe
format_sse(event) -> {"event": str, "data": json}   # sse-starlette kwargs
```

### Guardrails — `app.guardrails`

```python
ApprovalState.PENDING | APPROVED | REJECTED
@dataclass ApprovalRequest(id, tool_name, actor, approver_role, rationale,
                           correlation_id, created_at, evidence, state,
                           decided_at, decided_by, reject_reason)
@dataclass(frozen) GateOutcome(executed: bool, output, request)
ApprovalNotFoundError, InvalidTransitionError

class GuardrailEngine(*, audit, clock=now, id_factory=None):
    async submit(tool, payload, *, actor, approver_role, rationale="",
                 evidence=None, correlation_id=None) -> GateOutcome
        # non-consequential -> runs now; consequential -> DEFAULT-DENY, held
    async approve(request_id, *, approver) -> GateOutcome   # runs the held action
    async reject(request_id, *, approver, reason="") -> GateOutcome
    get(request_id) -> ApprovalRequest
    pending() -> list[ApprovalRequest]
```

**Every consequential action goes through `submit`. Default-deny. Approval, grant,
and rejection are all written to the audit log.**

### Audit — `app.audit`

```python
@dataclass(frozen) AuditEvent(id, timestamp, actor, action, payload, correlation_id)
class InMemoryAuditLog(*, clock=now, id_factory=None):   # append-only, immutable
    async record(*, actor, action, payload, correlation_id=None) -> AuditEvent
    async events(*, correlation_id=None) -> tuple[AuditEvent, ...]
```

### App wiring — `app.api.context`, `app.main`, `app.agents.discovery`

```python
@dataclass AppContext(audit, guardrails, jobs, gateway, connectors)
build_context() -> AppContext                # default in-process fakes
get_context(request) -> AppContext           # FastAPI dependency

create_app(context=None) -> FastAPI          # includes platform + discovered routers

# Router auto-discovery (parallel-safe registration)
discover_routers(package_names=AGENT_PACKAGES) -> list[APIRouter]
# A group-agent is found automatically if it exposes a module-level `router`
# (APIRouter) in `app.agents.<area>.<group>.router` (or the package __init__).
# DO NOT hand-edit a shared registry.
```

### Platform HTTP API (shared, owned by foundation)

```
GET  /health
GET  /approvals                      -> [ApprovalView]
POST /approvals/{id}/approve  {approver}          -> DecisionResult (404/409)
POST /approvals/{id}/reject   {approver, reason}  -> DecisionResult (404/409)
GET  /jobs/{id}                      -> JobView (404)
GET  /jobs/{id}/events               -> text/event-stream (SSE)
```

Group-agents add their own routes under `POST /agents/<group>/...`.

---

## Frontend (`frontend/src`)

```ts
// lib/types.ts  — Approval, DecisionResult, Job, JobEvent, ApprovalState, JobStatus
// lib/api.ts
listApprovals(): Promise<Approval[]>
approveRequest(id, approver): Promise<DecisionResult>
rejectRequest(id, approver, reason): Promise<DecisionResult>
getJob(id): Promise<Job>

// lib/sse.ts
subscribeJob(jobId, { onEvent, onError? }, EventSourceImpl?): () => void   // returns unsubscribe

// lib/auth.ts  (stub; swap internals for OIDC/SSO, keep signatures)
login(token) / logout() / getToken() / isAuthenticated() / authHeaders()

// components (props shapes are frozen)
<ApprovalDrawer approval onApprove(approver) onReject(approver, reason) onClose />
<JobTimeline events={JobEvent[]} />
```

---

## Module / test layout every group-agent copies

See `backend/app/agents/_template/` (a complete, tested reference). Copy it to
`app/agents/enterprise/<group>/` or `app/agents/financial_services/<group>/`:

```
<group>/  __init__.py  schemas.py  subagents.py  orchestrator.py  service.py  router.py
tests/agents/<area>/<group>/  test_orchestrator.py  test_subagents.py  test_router.py
```

Honor the spec's orchestration choice and **assert concurrency/ordering** in
tests. Add a test proving every consequential action is blocked without approval.

## Definition of Done (every session)

All tests green · `mypy` / `ruff` / `tsc` / `eslint` clean · coverage ≥ 85% on new
code · commit on the session's branch.
