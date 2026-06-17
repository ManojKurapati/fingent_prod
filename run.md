# run.md — Run, Containerise, Deploy & Use the Platform

Operational guide for the **AI-Native Finance Platform**. For vision and
architecture see [CLAUDE.md](CLAUDE.md); for the dev workflow see
[README.md](README.md); for the frozen interfaces see [CONTRACTS.md](CONTRACTS.md).

> **What runs today.** This repo is the **shared platform + group-agents** wave.
> The default backend boots with **in-memory fakes** (audit log, job queue,
> connectors) and a **stub Claude transport** — so it starts with **no API key
> and no database**. Postgres, Redis, and a real Anthropic transport are in the
> target architecture (CLAUDE.md §3) but are **not yet wired into the app
> context** ([backend/app/api/context.py](backend/app/api/context.py)). Treat
> them as planned wherever this guide says "planned".

---

## 0. Prerequisites

| Tool | Version | Used for |
|------|---------|----------|
| Python | 3.12+ | backend |
| [uv](https://docs.astral.sh/uv/) | latest | backend deps/run |
| Node | 20+ | frontend |
| npm | 10+ | frontend deps/run |
| Docker + Compose | recent | containers |

---

## 1. Run locally (no containers)

Two processes: the FastAPI backend on **:8000** and the Vite dev server on
**:5173** (which proxies API calls to the backend).

### Backend
```bash
cd backend
uv sync                                   # install deps
uv run uvicorn app.main:app --reload      # serves http://127.0.0.1:8000
```
- Health check: <http://127.0.0.1:8000/health> → `{"status":"ok"}`
- Interactive API docs (all agent + platform endpoints): <http://127.0.0.1:8000/docs>

### Frontend
```bash
cd frontend
npm install
npm run dev                               # serves http://127.0.0.1:5173
```
The dev server proxies `/health`, `/approvals`, `/jobs`, `/agents` to
`VITE_PROXY_TARGET` (default `http://127.0.0.1:8000`) — see
[frontend/vite.config.ts](frontend/vite.config.ts).

### Seeded demo backend (optional)
For a backend whose flows reach a decision (FP&A variance breach → commentary
approval; a trading order → routing approval) with an **auto-draining** job
queue, run the e2e server instead of `app.main`:
```bash
cd backend
uv run uvicorn app.e2e_server:app --port 8000
```

### Tests / quality gates
```bash
# backend
cd backend && make check     # ruff lint + mypy (strict) + coverage ≥85%
# frontend
cd frontend && npm run lint && npm run typecheck && npm run cov
cd frontend && npm run test:e2e   # Playwright (drives app.e2e_server)
```

---

## 2. Containerise (Docker)

Artifacts in the repo:

| File | Builds |
|------|--------|
| [backend/Dockerfile](backend/Dockerfile) | uv-based Python 3.12 image, runs uvicorn on :8000 |
| [frontend/Dockerfile](frontend/Dockerfile) | multi-stage Vite build → nginx serving on :80 |
| [frontend/nginx.conf](frontend/nginx.conf) | static SPA + reverse-proxy of API paths to `backend:8000` (SSE-aware) |
| [docker-compose.yml](docker-compose.yml) | backend + frontend wired together |

### One command (recommended)
```bash
cp .env.example .env        # optional today; fill ANTHROPIC_API_KEY when transport is wired
docker compose up --build
```
- Frontend (UI): <http://localhost:8080>
- Backend (API + docs): <http://localhost:8000/docs>

Compose waits for the backend `/health` healthcheck before starting the
frontend. Stop with `docker compose down`.

### Build / run images individually
```bash
# backend
docker build -t finance-platform-backend ./backend
docker run -p 8000:8000 --env-file .env finance-platform-backend

# frontend (expects a reachable backend; nginx proxies to host "backend")
docker build -t finance-platform-frontend ./frontend
docker run -p 8080:80 finance-platform-frontend
```

> The frontend image calls the API with **relative paths**, so nginx in the
> container forwards them to the `backend` service. If you serve the static
> bundle from elsewhere (CDN), set `VITE_API_URL` at **build time** to the
> backend's public URL.

---

## 3. Deploy to the cloud

The platform is two stateless containers, so any container host works. Pattern
is the same everywhere: **build → push to a registry → run the two images →
front them with TLS**.

### Build & push to a registry
```bash
docker build -t <registry>/finance-backend:<tag> ./backend
docker build -t <registry>/finance-frontend:<tag> ./frontend
docker push <registry>/finance-backend:<tag>
docker push <registry>/finance-frontend:<tag>
```
`<registry>` = e.g. `ghcr.io/<org>`, `<acct>.dkr.ecr.<region>.amazonaws.com`,
`<region>-docker.pkg.dev/<project>/<repo>`.

### Option A — managed container service (Cloud Run / ECS / Container Apps)
Deploy each image as its own service:
- **backend** — port 8000; set env (`ANTHROPIC_API_KEY` once wired); allow
  internal/public ingress; the platform is async and streams SSE, so allow
  long-lived responses and avoid aggressive response buffering on `/jobs/*/events`.
- **frontend** — port 80; public ingress behind the platform's TLS/HTTPS.
  Either keep the nginx proxy (point it at the backend's internal URL) or build
  the bundle with `VITE_API_URL=https://<backend-url>` and host the static files
  directly.

Example (Google Cloud Run):
```bash
gcloud run deploy finance-backend  --image <registry>/finance-backend:<tag>  --port 8000 --allow-unauthenticated
gcloud run deploy finance-frontend --image <registry>/finance-frontend:<tag> --port 80   --allow-unauthenticated
```

### Option B — single VM with Compose
```bash
# on the host, with the repo (or just docker-compose.yml + images) present
cp .env.example .env && $EDITOR .env
docker compose up -d --build
```
Put a reverse proxy / TLS terminator (Caddy, Traefik, nginx, or a cloud LB) in
front of port 8080.

### Production checklist (before real money/data)
This wave ships the platform; production wiring still required — see
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Notably:
- Wire the **real Anthropic transport** into the gateway and supply `ANTHROPIC_API_KEY` via a secrets manager (never bake into images).
- Replace in-memory **audit log / job queue** with **Postgres + Redis** (uncomment the `db`/`redis` services in [docker-compose.yml](docker-compose.yml) and wire them into the app context).
- Add **auth (OIDC/SSO) + RBAC**, CORS, rate limits, and TLS.
- Run the job **worker fleet** out-of-process (e.g. arq/Celery) instead of inline draining.
- Observability: tracing per agent run, cost/latency dashboards (scaffolding under [backend/app/observability/](backend/app/observability/)).

---

## 4. Environment keys

Copy [.env.example](.env.example) → `.env` (git-ignored). **None are required
to run the foundation locally today.**

| Key | Scope | Status | Purpose |
|-----|-------|--------|---------|
| `ANTHROPIC_API_KEY` | backend | **planned** | Auth for the real Claude transport. Default context uses a no-network stub, so unset = fine today. |
| `VITE_API_URL` | frontend (build-time) | active | Base URL the React app calls. Empty = relative paths (nginx/dev-proxy forward them). |
| `VITE_PROXY_TARGET` | frontend (dev only) | active | Backend the Vite dev server + Playwright proxy to. Default `http://127.0.0.1:8000`. |
| `DATABASE_URL` | backend | planned | Postgres (system of record / jobs / audit). Not yet read by app code. |
| `REDIS_URL` | backend | planned | Redis (queue + cache). Not yet read by app code. |

Secrets rule: in cloud, inject via the platform's secret store / env, never
commit `.env` or bake keys into an image.

---

## 5. How to use the platform

The platform exposes **shared platform endpoints** + one router per group-agent.
Browse and try everything live at **`/docs`** (Swagger UI).

### Shared platform endpoints
Defined in [backend/app/api/platform.py](backend/app/api/platform.py):

| Method & path | Purpose |
|---------------|---------|
| `GET /health` | liveness |
| `GET /approvals` | list pending human-in-the-loop approval requests |
| `POST /approvals/{id}/approve` | approve → executes the gated action; body `{"approver":"..."}` |
| `POST /approvals/{id}/reject` | reject; body `{"approver":"...","reason":"..."}` |
| `GET /jobs/{id}` | job status / result |
| `GET /jobs/{id}/events` | **SSE** stream of per-subagent progress |

### Group-agent endpoints (auto-discovered)
Each group mounts under `/agents/<group>`. Enterprise: `fpa`, `accounting`,
`tax`, `treasury`, `transactional`, `finops`, `corpdev`, `audit`, `leadership`.
Financial services: `risk`, `compliance`, `investment-banking`,
`sales-trading-markets`, `asset-investment-management`, `quant`, `insurance`,
`ops`, `retail-commercial-banking`, `wealth-private-banking`, `private-markets`,
`product`. (See `/docs` for each one's request schema.)

### The core flow (run → stream → approve)
Every agent run is **enqueued** (returns a `job_id` immediately), streams
progress over SSE, and routes any **consequential action** to the approval
queue. Example with the seeded e2e backend (`uvicorn app.e2e_server:app`):

```bash
# 1) Kick off an FP&A forecast run (cc1 is seeded to breach its variance threshold)
curl -s -X POST http://localhost:8000/agents/fpa/forecast \
  -H 'content-type: application/json' \
  -d '{"period":"2026-Q3","cost_centres":["cc1","cc2"],"variance_threshold":0.1}'
# -> {"job_id":"..."}

# 2) Watch progress stream (Ctrl-C to stop)
curl -N http://localhost:8000/jobs/<job_id>/events

# 3) The variance breach raised an approval — list it
curl -s http://localhost:8000/approvals
# -> [{"id":"...","tool_name":"...","rationale":"...","state":"pending", ...}]

# 4) A human approves -> the gated action executes
curl -s -X POST http://localhost:8000/approvals/<approval_id>/approve \
  -H 'content-type: application/json' -d '{"approver":"cfo@firm.com"}'
# -> {"executed":true, "request":{...,"state":"approved"}}
```

In the **UI** (`:5173` dev or `:8080` container) the same flow is visual: trigger
a run, the **JobTimeline** streams subagent progress, and the **ApprovalDrawer**
surfaces consequential actions for approve/reject. Nothing that posts to a
ledger, moves cash, trades, binds risk, lends, or files externally executes
until a human approves it — that gate is enforced by the guardrail engine, not
optional UI.

### Adding a new group-agent
Copy [backend/app/agents/_template/](backend/app/agents/_template/) to
`app/agents/<domain>/<group>/`, expose a module-level `router`, and it is
auto-discovered — no registry to edit. Follow STRICT TDD per
[build.md](build.md) and honour the orchestration choice in the spec.
