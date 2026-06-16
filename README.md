# AI-Native Finance Platform — Foundation

Shared platform (wave 0) for an AI-native finance organisation: orchestrated AI
agents with a human in the loop on every consequential action. This wave ships
**only the shared platform** — no business agents yet.

See [CLAUDE.md](CLAUDE.md) for vision/architecture, [build.md](build.md) for the
multi-session TDD runbook, and **[CONTRACTS.md](CONTRACTS.md)** for the frozen
interfaces every group-agent imports.

## Layout

```
backend/    FastAPI + agent core + connectors + jobs + guardrails + audit + template
frontend/   React + TS + Vite shell (SSE/API clients, auth stub, ApprovalDrawer, JobTimeline)
```

## Backend (Python 3.12, uv)

```bash
cd backend
uv sync                 # install
make test               # pytest
make cov                # coverage (fails under 85%)
make lint               # ruff check + format --check
make typecheck          # mypy (strict)
make check              # lint + typecheck + cov
uv run uvicorn app.main:app --reload   # run the API
```

## Frontend (Node 20, npm)

```bash
cd frontend
npm install
npm test                # vitest
npm run cov             # vitest --coverage (85% thresholds)
npm run lint            # eslint
npm run typecheck       # tsc --noEmit
npm run dev             # vite dev server
```

## What's here

- **Agent core** — `Subagent`, `BaseOrchestrator`, and a deterministic runner for
  `SEQUENTIAL` / `PARALLEL` / `HYBRID` step graphs; a `ClaudeGateway` (Opus/Haiku
  routing, retries, token accounting).
- **Connectors** — typed `Tool` base with a `consequential` flag + a fake.
- **Jobs** — async queue (idempotency + retries) + SSE progress streaming + fake.
- **Guardrails** — default-deny approval engine intercepting consequential tool
  calls; immutable **audit log**.
- **Template** — `backend/app/agents/_template/`, a complete, tested reference
  group-agent that wave 2/3 sessions copy. Routers auto-discover — no shared
  registry to hand-edit.
- **Frontend shell** — API + SSE clients, auth stub, and reusable `ApprovalDrawer`
  + `JobTimeline` components.

Everything is built test-first; the suite, types, and linters are green and
coverage is ≥ 85% on both sides.

## Building a group-agent

Copy `backend/app/agents/_template/` to `app/agents/enterprise/<group>/` (or
`financial_services/<group>/`), rename `template` → your group, and follow STRICT
TDD per [build.md](build.md). Honor the orchestration choice in the spec and prove
every consequential action is gated.
