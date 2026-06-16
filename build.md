# Build Plan — Multi-Session TDD Execution

How to build the AI-native finance platform using **multiple Claude Code sessions in VS Code**, with **strict test-driven development**. This document gives you the exact prompts to paste into each session and tells you what to run **sequentially** vs **in parallel**.

Read [CLAUDE.md](CLAUDE.md) first for the architecture; this doc is the execution runbook.

---

## 0. Core principles (read once)

1. **TDD always.** Every session writes **failing tests first** (RED), implements the minimum to pass (GREEN), then refactors (REFACTOR). No implementation code before a failing test exists.
2. **Contracts before parallelism.** Shared interfaces (agent base classes, the `Tool` interface, API/SSE schemas, DB models) are built and frozen in the **foundation wave** so parallel sessions code against stable, unchanging contracts.
3. **One owner per file.** Parallel sessions must edit **disjoint file sets**. Two sessions never touch the same file. Agent modules are naturally isolated — that's why they parallelize cleanly.
4. **Isolation via git worktrees.** Each parallel session runs in its **own git worktree + branch**, so there are zero working-tree collisions. Integrate via PR/merge.
5. **No core edits from feature sessions.** If a parallel session thinks it needs to change shared core, it **stops and reports** instead of editing it. Core changes happen only in the foundation/integration session.
6. **Definition of Done (every session):** all tests green, type-checks pass (`mypy` / `tsc`), linter clean (`ruff` / `eslint`), coverage ≥ 85% on new code, and a commit on its branch.

---

## 1. One-time setup

```bash
cd /Users/klm/Adv.rag
git add -A && git commit -m "docs: roles, agent specs, build plan"   # baseline

# Worktrees live as sibling folders so each VS Code window opens a clean tree.
# (Create these only when a wave needs them — listed per wave below.)
git worktree add ../Adv.rag-foundation  -b foundation
```

**Running N sessions in VS Code (recommended):**
- **One VS Code window per worktree** (`File → New Window → Open Folder → ../Adv.rag-<name>`). Launch Claude Code in each window's terminal. This is the safe model — each window edits its own tree.
- Avoid running multiple *editing* sessions against the **same** folder (they will clobber each other's files). Multiple terminals in one window is fine only for read-only/observer sessions.
- Keep a **conductor** window open on the main repo for merges, running the full suite, and reviewing PRs.

**Test tooling (set up in Wave 0):**
- Backend: `pytest`, `pytest-asyncio`, `httpx` (API tests), `pytest-cov`, `respx`/`responses` (mock connectors), `freezegun`.
- Frontend: `vitest` + React Testing Library (unit), `msw` (mock API/SSE), `playwright` (e2e).

---

## 2. Wave map (the schedule)

| Wave | Sessions | Mode | Depends on | Goal |
|------|----------|------|-----------|------|
| **0 — Foundation** | 1 | Sequential (blocking) | — | Platform, contracts, test harness, guardrails |
| **1 — Reference slice** | 1 | Sequential (blocking) | Wave 0 | FP&A agent built TDD as the copy-paste template |
| **2 — Enterprise agents** | up to 4 | **Parallel** | Wave 1 | Remaining 8 enterprise group-agents |
| **3 — Financial-services agents** | up to 4 | **Parallel** | Wave 1 | 12 financial-services group-agents |
| **4 — Integration & hardening** | 1 | Sequential | Waves 2 & 3 | Merge, cross-agent orchestration, e2e, perf |

> Waves 2 and 3 are independent of each other and *can* overlap if you have the machine + attention for 8 windows. Most people should do **Wave 2, merge, then Wave 3**. Tune parallelism to your CPU and your ability to review.

**Recommended max parallel = 4.** More windows = more merge/review overhead than a human can track.

---

## 3. WAVE 0 — Foundation (1 session, run alone)

Open the `../Adv.rag-foundation` worktree in a VS Code window. Paste this prompt:

```
You are building the foundation of an AI-native finance platform. Read CLAUDE.md, claude1.md, and claude2.md fully before doing anything.

We use STRICT TDD. For every unit of work: write a failing test first, run it to confirm it fails, write the minimum code to pass, then refactor. Never write implementation before a failing test.

Build ONLY the shared platform in this wave — no business agents yet. Deliver, test-first, in this order:

1. Repo scaffold: backend/ (FastAPI, Python 3.12, async) and frontend/ (React + TS + Vite). Set up pytest + pytest-asyncio + pytest-cov + httpx for backend, and vitest + React Testing Library + msw for frontend. Add ruff, mypy, eslint, tsc, and a pre-commit config. Add a Makefile / npm scripts: `test`, `lint`, `typecheck`, `cov`.
2. Agent core (backend/app/agents/core/): BaseOrchestrator, Subagent abstraction, a deterministic orchestration runner supporting SEQUENTIAL, PARALLEL, and HYBRID step graphs, and a Claude API gateway (model routing Opus/Haiku, retries, token accounting). These are the FROZEN CONTRACTS other sessions depend on — design the interfaces carefully and document them.
3. Tool/connector interface (backend/app/connectors/): a typed `Tool` base with a `consequential: bool` flag. Provide one fake in-memory connector for tests.
4. Job system (backend/app/jobs/): async queue abstraction (Redis/arq) with idempotency + retries, plus SSE progress streaming. Provide an in-memory fake for tests.
5. Guardrail/approval engine (backend/app/guardrails/): intercepts any consequential tool call and creates an approval request; default-deny until approved. Immutable audit log (backend/app/audit/).
6. A documented "agent module template" under backend/app/agents/_template/ showing the exact file layout, test layout, and router pattern a group-agent must follow. THIS IS WHAT WAVE 2/3 SESSIONS COPY.
7. Frontend shell: app skeleton, SSE client, API client, auth stub, and a reusable ApprovalDrawer + JobTimeline component with tests.

Output a short CONTRACTS.md at repo root listing every interface other sessions import and MUST NOT modify. Commit on the `foundation` branch. Definition of done: all tests pass, mypy/ruff/tsc/eslint clean, coverage >=85% on new code.
```

**After it finishes:** review, run the full suite yourself, then merge `foundation` → `main`. Everything below branches from this.

---

## 4. WAVE 1 — Reference vertical slice: FP&A (1 session, run alone)

This builds **one complete agent** end-to-end as the template every parallel session imitates. Pick FP&A because its parallel fan-out (forecast ‖ variance ‖ scenario) exercises the whole orchestration + SSE + approval stack.

```bash
git worktree add ../Adv.rag-fpa -b agent/fpa main   # main now includes foundation
```

Open `../Adv.rag-fpa`. Paste:

```
Read CLAUDE.md, claude1.md (section "2. FP&A Agent"), enterprise-finance/fpa.md, CONTRACTS.md, and backend/app/agents/_template/. Follow STRICT TDD throughout: failing test first, confirm red, minimal code to green, refactor.

Build the FP&A group-agent as the REFERENCE IMPLEMENTATION other agents will copy. You may ONLY create/edit files under backend/app/agents/enterprise/fpa/, its tests, frontend/src/pages/fpa/, and the FP&A router registration. DO NOT modify anything in backend/app/agents/core/, connectors/, jobs/, guardrails/, or CONTRACTS.md — if you think you need to, STOP and report why.

Implement per claude1.md's orchestration for FP&A:
- Subagents: data-intake, budget-consolidation, forecast-engine, variance-analysis, revenue-analytics, scenario-modelling, reporting-packs.
- Orchestration: sequential intake -> consolidation, then PARALLEL fan-out (forecast ‖ variance-per-cost-centre ‖ revenue ‖ scenario), fan-in -> reporting pack streamed over SSE.
- FastAPI: POST /agents/fpa/forecast (enqueue job -> workers -> SSE), POST /agents/fpa/scenario.
- React: planning dashboard, live variance grid that turns green as workers finish, scenario sandbox, human-in-the-loop variance-commentary approval.

Write tests for: each subagent (mocked Claude + fake connectors), the orchestrator graph (assert parallel steps actually run concurrently and sequential ordering holds), the API endpoints (httpx), SSE progress events, and a frontend test for the approval flow (msw-mocked). Commit on branch agent/fpa. DoD: all green, types + lint clean, coverage >=85%, and write a 10-line NOTES_FOR_TEMPLATE.md describing what other agent sessions should copy.
```

**After it finishes:** review, merge `agent/fpa` → `main`. Now the template is proven. Parallel waves can start.

---

## 5. WAVE 2 — Enterprise agents (up to 4 parallel sessions)

Each session = its own worktree/branch, owns a disjoint set of agent modules. Create the worktrees:

```bash
git worktree add ../Adv.rag-E1 -b agents/enterprise-1 main
git worktree add ../Adv.rag-E2 -b agents/enterprise-2 main
git worktree add ../Adv.rag-E3 -b agents/enterprise-3 main
git worktree add ../Adv.rag-E4 -b agents/enterprise-4 main
```

| Session | Worktree | Owns (group agents) |
|---------|----------|---------------------|
| E1 | ../Adv.rag-E1 | `leadership`, `corporate-development-strategy` |
| E2 | ../Adv.rag-E2 | `accounting-controllership`, `treasury` |
| E3 | ../Adv.rag-E3 | `transactional-finance`, `tax` |
| E4 | ../Adv.rag-E4 | `internal-audit-controls`, `finance-systems-operations` |

**Run all four in parallel** (separate VS Code windows). Paste this into each, swapping the two bracketed values:

```
Read CLAUDE.md, claude1.md, CONTRACTS.md, backend/app/agents/_template/, and the reference implementation under backend/app/agents/enterprise/fpa/ plus NOTES_FOR_TEMPLATE.md. Copy that proven pattern.

You are building these enterprise group-agents ONLY: [GROUP_A] and [GROUP_B].
For each, read its spec file enterprise-finance/[GROUP].md (responsibilities) and the matching "## N. ... Agent" section of claude1.md (subagents + orchestration choice + FastAPI/React).

STRICT TDD: for every subagent, orchestrator, and endpoint — write the failing test first, confirm it fails, write minimal code to pass, then refactor.

OWNERSHIP RULES (critical for parallel safety): you may ONLY create/edit files under backend/app/agents/enterprise/[GROUP_A]/, backend/app/agents/enterprise/[GROUP_B]/, their tests, and frontend/src/pages/[GROUP]/. You MUST NOT edit core/, connectors/, jobs/, guardrails/, audit/, CONTRACTS.md, or any other agent's folder. For router registration, only add your two routers — if registration requires touching a shared file that another session also edits, instead expose your router via the documented auto-discovery mechanism from the template (do not hand-edit a shared registry). If you believe you need a core change, STOP and report.

Honor each agent's orchestration choice from claude1.md exactly (sequential where data depends, parallel where independent, hybrid otherwise). Write tests that ASSERT the concurrency/ordering behavior. Any consequential action (ledger post, payment, external filing) must route through the guardrail engine — test that it is blocked without approval.

Commit on your branch. DoD: all tests green, mypy/ruff/tsc/eslint clean, coverage >=85% on new code. Produce a short summary of files added.
```

**After all four finish:** merge branches **one at a time** into `main` from the conductor window, running the **full test suite after each merge**. Because file sets are disjoint, conflicts should be limited to router auto-discovery (handled by the template) — resolve any, keep the suite green.

---

## 6. WAVE 3 — Financial-services agents (up to 4 parallel sessions)

Same model. Create worktrees from the now-updated `main`:

```bash
git worktree add ../Adv.rag-F1 -b agents/fs-1 main
git worktree add ../Adv.rag-F2 -b agents/fs-2 main
git worktree add ../Adv.rag-F3 -b agents/fs-3 main
git worktree add ../Adv.rag-F4 -b agents/fs-4 main
```

| Session | Worktree | Owns (group agents) |
|---------|----------|---------------------|
| F1 | ../Adv.rag-F1 | `investment-banking`, `sales-trading-markets`, `asset-investment-management` |
| F2 | ../Adv.rag-F2 | `private-markets`, `wealth-private-banking`, `retail-commercial-banking` |
| F3 | ../Adv.rag-F3 | `insurance`, `risk-management`, `compliance-legal-financial-crime` |
| F4 | ../Adv.rag-F4 | `operations-middle-back-office`, `quantitative-data-technology`, `product-strategy-client` |

Paste into each (swap the three bracketed groups):

```
Read CLAUDE.md, claude2.md, CONTRACTS.md, backend/app/agents/_template/, and the reference implementation under backend/app/agents/enterprise/fpa/ plus NOTES_FOR_TEMPLATE.md. Copy that proven pattern (financial-services agents live under backend/app/agents/financial_services/).

You are building these financial-services group-agents ONLY: [GROUP_A], [GROUP_B], [GROUP_C].
For each, read financial-services/[GROUP].md and the matching "## N. ... Agent" section of claude2.md.

STRICT TDD: failing test first -> confirm red -> minimal code to green -> refactor, for every subagent, orchestrator, and endpoint.

OWNERSHIP RULES: you may ONLY create/edit files under backend/app/agents/financial_services/[your three groups]/, their tests, and frontend/src/pages/[group]/. You MUST NOT edit core/, connectors/, jobs/, guardrails/, audit/, CONTRACTS.md, or any other agent's folder. Register routers only via the template's auto-discovery mechanism. If you need a core change, STOP and report.

CRITICAL — financial-services guardrails: risk and compliance checks are MANDATORY pre-execution gates. Any trade / bind / lend / external filing must pass the guardrail engine AND, where claude2.md specifies, a risk or compliance check, BEFORE execution. Write tests proving execution is blocked when a gate fails or approval is missing. Honor each agent's sequential/parallel/hybrid orchestration from claude2.md and assert it in tests.

Commit on your branch. DoD: all green, types + lint clean, coverage >=85%. Summarize files added.
```

**After all four finish:** merge one at a time into `main`, running the full suite after each.

---

## 7. WAVE 4 — Integration & hardening (1 session, run alone)

```bash
git worktree add ../Adv.rag-integration -b integration main
```

```
Read CLAUDE.md and CONTRACTS.md. All 21 group-agents are now merged on main. STRICT TDD for everything new.

Tasks (test-first):
1. Cross-agent orchestration: the Leadership/CFO agent can invoke other enterprise agents; the chain research -> portfolio -> trading -> operations works in financial services. Write integration tests for one enterprise chain and one financial-services chain end to end (mocked Claude + fake connectors).
2. Global guardrail audit: write a test that scans every registered tool flagged consequential=True and asserts it is unreachable without an approval record. Fail the build if any consequential action bypasses the gate.
3. E2E (Playwright): one enterprise flow (FP&A forecast -> approval -> report) and one financial-services flow (trade request -> risk gate -> compliance gate -> approval) through the real React UI against the running FastAPI app with fakes.
4. Observability: per-agent run tracing, token/cost + latency capture; a test asserting every agent run emits a trace span and an audit event.
5. Performance: a load test of a parallel fan-out agent (e.g. variance across many cost centres) asserting bounded concurrency and no double-execution under retries.

DoD: full suite green (unit + integration + e2e), coverage maintained, lint/type clean. Write a RELEASE_CHECKLIST.md for production (secrets/vault, RBAC/SSO, DB migrations, backups/DR, rate limits). Commit on branch integration.
```

Merge `integration` → `main` after review.

---

## 8. Best-practices checklist (pin this)

- [ ] **RED first, always.** If a session writes code before a failing test, stop it and tell it to delete and restart TDD.
- [ ] **One worktree + branch per parallel session.** Never two editing sessions on the same folder.
- [ ] **Disjoint file ownership.** Confirm each parallel session's owned paths don't overlap before you start the wave.
- [ ] **Contracts are frozen.** Feature sessions import from core; they never edit it. Core changes = foundation/integration session only.
- [ ] **Merge serially, test after each merge.** Keep `main` green at all times.
- [ ] **Review before merge.** Skim the diff and the tests; the tests are the spec — make sure they assert real behavior (concurrency, guardrail blocking), not just "returns 200".
- [ ] **Guardrails are tested, not assumed.** Every consequential action must have a test proving it's blocked without approval.
- [ ] **Tune parallelism to what you can review.** 4 windows is plenty. Quality of review is the real bottleneck, not the agents.
- [ ] **Clean up worktrees** when a wave merges: `git worktree remove ../Adv.rag-<name>`.

---

## 9. Quick reference — what runs when

```
Wave 0 Foundation            [ run ALONE ]                  -> merge to main
Wave 1 FP&A reference        [ run ALONE ]                  -> merge to main
Wave 2 Enterprise  E1 E2 E3 E4   [ run in PARALLEL ]        -> merge serially
Wave 3 Fin-services F1 F2 F3 F4  [ run in PARALLEL ]        -> merge serially
Wave 4 Integration           [ run ALONE ]                  -> merge to main
```
Sequential between waves; parallel within waves 2 and 3.
