# AI-Native Finance Organisation

> I am working on creating an AI-native finance organisation: a platform where the work of a full finance org — both the in-house finance function and financial-services lines of business — is executed by orchestrated AI agents with humans in the loop on every consequential action.

This file is the top-level project context and build plan. It points to the detailed design docs and the role catalogue.

---

## 1. Vision

Replace the org chart with an **agent chart**. Every functional group in a finance organisation becomes an **orchestrator agent**; every responsibility within that group becomes a **subagent task**. Agents run sequentially, in parallel, or in hybrid flows depending on data dependencies. Humans approve anything that posts to a ledger, moves cash, executes a trade, binds risk, lends, or files externally.

The product is not a chatbot. It is a **system of autonomous-but-governed finance workers** exposed through dashboards, approval queues, and audit trails.

---

## 2. Source-of-truth documents

| Doc | What it contains |
|-----|------------------|
| [roles.md](roles.md) | Full catalogue of finance roles across Enterprise Finance, Financial Services, and cross-cutting. |
| [claude1.md](claude1.md) | Build context for the **9 Enterprise Finance** group-agents — subagents, orchestration choice (sequential/parallel/hybrid), FastAPI + React patterns. |
| [claude2.md](claude2.md) | Build context for the **12 Financial Services** group-agents — same structure, plus mandatory risk/compliance gates. |
| [enterprise-finance/](enterprise-finance/) | Per-group role + responsibility files (9). |
| [financial-services/](financial-services/) | Per-group role + responsibility files (12). |
| [mixed/](mixed/) | Cross-cutting roles that span both contexts (1). |

When implementing any agent, read its group file (responsibilities) and the matching section of claude1.md / claude2.md (orchestration + endpoints) first.

---

## 3. Tech stack

- **Backend:** FastAPI (async), Python 3.12+. One service that hosts the agent runtime + REST/SSE API.
- **Frontend:** React (TypeScript) + Vite. Dashboards, approval queues, human-in-the-loop drawers.
- **Agent runtime:** Python orchestration layer (LangGraph-style state machine or a thin custom orchestrator) over the **Claude API** (Opus for reasoning/orchestration, Haiku for cheap high-volume subagent tasks).
- **Async / fan-out:** `asyncio` for in-process concurrency; a task queue (Celery or arq + Redis) for long-running parallel subagent fan-out and retries.
- **Streaming:** SSE (or websockets) to stream per-subagent progress to React.
- **Data:** Postgres (system of record, jobs, audit log), Redis (queue + cache), a vector store (pgvector or Qdrant) for agent memory/RAG over policies, filings, and prior decisions.
- **Connectors:** a tool/connector layer abstracting ERP/GL, bank APIs, market data, CRM, document stores — each exposed to agents as typed tools.
- **Auth & governance:** OIDC/SSO, RBAC, per-action approval policy engine, immutable audit log.

---

## 4. Architecture (shared across both domains)

```
React UI ──REST/SSE──► FastAPI ──► Orchestrator Agent (per group)
                          │              │
                          │              ├─► Subagent task ─┐
                          │              ├─► Subagent task ─┼─► Tool/Connector layer ─► ERP / Banks / Market data
                          │              └─► Subagent task ─┘        │
                          │                                          ├─► Postgres (records, jobs)
                          ▼                                          ├─► Vector store (memory/RAG)
                  Job queue (Redis) ◄── workers ──────────────────► └─► Audit log (immutable)
                          │
                  Approval / Guardrail engine ──► Human-in-the-loop queue (React)
```

- **Orchestrator agent** = group (e.g. FP&A, Trading). Owns a plan and dispatches subagents.
- **Subagent** = one responsibility cluster. Runs as an async task or a queued worker job.
- **Orchestration pattern** per group is fixed in claude1/claude2 (sequential where data depends, parallel where independent, hybrid otherwise).
- **Guardrail engine** intercepts any "consequential action" tool call and routes it to a human approval queue before execution.

---

## 5. Repository layout (target)

```
/
├── CLAUDE.md, roles.md, claude1.md, claude2.md   # context & design
├── enterprise-finance/  financial-services/  mixed/   # role/responsibility specs
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app
│   │   ├── api/                     # routers per group (/agents/fpa, /agents/trading, ...)
│   │   ├── agents/                  # orchestrator + subagent definitions
│   │   │   ├── core/                # base agent, planner, tool runtime, memory
│   │   │   ├── enterprise/          # 9 group agents
│   │   │   └── financial_services/  # 12 group agents
│   │   ├── connectors/              # ERP, bank, market-data, CRM tools
│   │   ├── guardrails/              # approval policy engine
│   │   ├── jobs/                    # queue + workers
│   │   ├── models/                  # SQLAlchemy + Pydantic schemas
│   │   └── audit/                   # immutable event log
│   └── tests/
└── frontend/
    ├── src/
    │   ├── pages/                   # one dashboard per group agent
    │   ├── components/              # approval drawer, job timeline, exception queue
    │   └── lib/                     # SSE client, API client, auth
    └── ...
```

---

## 6. Build plan (phased)

### Phase 0 — Foundations (platform before agents)
- Scaffold FastAPI + React + Postgres + Redis; CI, lint, typecheck, pre-commit.
- Build the **agent core**: base orchestrator, subagent abstraction, tool runtime, Claude API gateway (model routing + retries + token accounting).
- Build the **job system** (queue, workers, SSE progress) and the **audit log**.
- Build the **guardrail/approval engine** and a generic **human-in-the-loop approval UI**. *Nothing ships without this.*

### Phase 1 — First vertical slice (prove the pattern end to end)
- Pick **one** high-value, well-bounded group with clear data dependencies. Recommended: **FP&A** (enterprise) — parallel forecast/variance/scenario fan-out is a clean demo of orchestration + SSE + approvals.
- Implement its orchestrator + subagents, connectors (read-only GL/actuals to start), dashboard, and approval flow.
- Establish the **reusable template** every other group will copy.

### Phase 2 — Enterprise Finance build-out
- Implement the remaining 8 enterprise group-agents per [claude1.md](claude1.md), reusing the Phase-1 template.
- Add write connectors (GL posting, payments) behind mandatory approval gates.
- Wire the **Leadership/CFO agent** to invoke other group agents (cross-agent orchestration).

### Phase 3 — Financial Services build-out
- Implement the 12 financial-services group-agents per [claude2.md](claude2.md).
- Make **risk + compliance checks mandatory pre-execution gates** for any trade / bind / lend / filing.
- Add market-data and trading/ops connectors (simulated/paper first, then live behind approvals).

### Phase 4 — Production hardening
- Observability (tracing per agent run, cost/latency dashboards, eval harness for agent quality).
- Security review, pen test, data-segregation, secrets management.
- Load testing of parallel fan-out; backpressure and rate-limit handling.
- DR, backups, and audit/regulatory reporting exports.

### Phase 5 — Scale & continuous improvement
- Agent memory/RAG over accumulated decisions and policies.
- Per-group evals + feedback loops; progressively widen autonomy where audit shows reliability.

---

## 7. Cross-cutting production requirements

- **Human-in-the-loop is non-negotiable** for consequential actions. Default-deny; explicit approval to execute.
- **Everything is audited.** Every agent decision, tool call, input, and approval is logged immutably with the model version and prompt.
- **Determinism where it matters.** Orchestration (who runs when) is deterministic code; only the reasoning inside a subagent is model-driven.
- **Idempotency & retries** on all queued jobs; no double-posting to ledgers or double-executing trades.
- **Least privilege** on every connector; secrets in a vault; per-tenant data isolation.
- **Evals before autonomy.** A subagent only earns reduced human oversight after measured accuracy on a golden dataset.

---

## 8. Conventions for contributors (and for Claude)

- Backend is async-first; subagent tasks must be cancellable and emit progress events.
- Each group agent lives in its own module and exposes a router under `/agents/<group>`.
- New connectors implement the typed `Tool` interface and declare whether they perform a **consequential action** (which forces a guardrail check).
- Read the relevant group spec + claude1/claude2 section before writing an agent. Keep the orchestration choice (sequential/parallel/hybrid) as documented unless a dependency analysis says otherwise — and update the doc if you change it.
