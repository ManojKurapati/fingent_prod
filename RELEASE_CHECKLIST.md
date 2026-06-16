# RELEASE_CHECKLIST — Production readiness

Gate for promoting the AI-native finance platform from the in-process fakes used in
dev/test to a hardened production deployment. **Nothing ships unless every box in
the "Blocking" sections is checked.** The platform's whole premise is *autonomous
but governed* — so the guardrail, audit, and human-in-the-loop guarantees are
release-blocking, not nice-to-haves.

Legend: **(C)** = touches a consequential action path (ledger post / payment / trade /
bind / lend / filing) — treat with extra scrutiny.

---

## 0. Pre-flight (every release)

- [ ] Full backend suite green: `cd backend && make check` (pytest + ruff + mypy, coverage ≥ 85%).
- [ ] Full frontend suite green: `cd frontend && npm run test && npm run lint && npm run typecheck && npm run cov`.
- [ ] E2E green: `cd frontend && npm run test:e2e` (FP&A forecast→approval→report; trade→risk-gate→approval).
- [ ] **Guardrail audit green** (C) — `test_guardrail_audit.py` passes: every `consequential=True` tool is default-denied and has no direct-`invoke` bypass. A red here blocks the release unconditionally.
- [ ] No `# TODO(security)` / `xfail` / `skip` on a consequential path.
- [ ] CHANGELOG / release notes updated; version bumped; git tag created.
- [ ] Rollback plan written and the previous image/tag known-good.

---

## 1. Secrets & vault — **Blocking**

- [ ] No secrets in source, env files, or the image. CI secret-scan (gitleaks/trufflehog) green.
- [ ] All credentials sourced from a vault (HashiCorp Vault / AWS Secrets Manager / GCP Secret Manager) at runtime; short-lived, auto-rotated.
- [ ] **Anthropic API key** in vault; the `ClaudeGateway` production transport reads it from the secret store, never from a literal. Per-environment keys (dev/stage/prod isolated).
- [ ] Connector credentials (ERP/GL, bank APIs, market data, CRM, custodian/CSD) (C) are least-privilege, per-tenant, and scoped to the minimum actions the tool declares.
- [ ] DB / Redis / vector-store credentials rotated; TLS enforced in transit; encryption at rest enabled.
- [ ] Key rotation runbook tested (rotate without downtime); break-glass procedure documented and access-logged.

## 2. AuthN / AuthZ — RBAC & SSO — **Blocking**

- [ ] OIDC/SSO wired (the `frontend/src/lib/auth.ts` stub replaced with real OIDC; signatures unchanged per CONTRACTS). MFA enforced for approver roles.
- [ ] RBAC enforced server-side on every route, not just in the UI. Roles map to the `approver_role` each consequential action requires (e.g. `cfo`, `trader`, `cro`, `mlro`, `chief-underwriter`, `underwriter`, `investment-committee`).
- [ ] **Approval authority is segregated** (C) — the actor who proposes an action can never approve it (no self-approval); approver role is checked against the request's required role.
- [ ] Service-to-service auth (mTLS / signed tokens) between API, workers, and connectors.
- [ ] Session expiry, refresh, and revocation tested; least-privilege on platform/admin endpoints.
- [ ] Per-tenant data isolation verified (no cross-tenant read of jobs, approvals, or audit).

## 3. Database & migrations — **Blocking**

- [ ] Postgres provisioned as system of record; the in-memory fakes (`InMemoryAuditLog`, `InMemoryJobQueue`, `GuardrailEngine` in-mem maps, `FakeStore`) replaced by persistent implementations behind the **same frozen contracts**.
- [ ] Migration tool (Alembic) configured; migrations are versioned, reviewed, and **forward-and-back tested** on a prod-like snapshot.
- [ ] Zero-downtime migration strategy (expand/contract); no destructive migration without a backout.
- [ ] **Audit log is append-only at the storage layer** (C) — `INSERT`-only grants, no `UPDATE`/`DELETE` for the app role; immutability enforced by DB permissions (and ideally WORM/retention policy), not just by code.
- [ ] Approval records, jobs, and audit events persisted with `correlation_id` lineage indexed for traceability.
- [ ] Idempotency keys persisted and unique-constrained so retries never double-post/double-trade across process restarts (C).

## 4. Backups & DR — **Blocking**

- [ ] Automated Postgres backups (PITR / WAL archiving); retention meets regulatory requirements.
- [ ] Backups encrypted and stored cross-region; **restore tested end to end** (not just "backups exist").
- [ ] Documented RPO/RTO; DR runbook rehearsed; failover for DB, Redis, and the API tier.
- [ ] Audit log backed up with the strongest retention/immutability tier (regulatory record) (C).
- [ ] Vector store / agent-memory rebuildable from source-of-truth (treat as cache, not SoR).
- [ ] Disaster game-day completed in the last quarter; results actioned.

## 5. Rate limits, quotas & backpressure — **Blocking**

- [ ] Inbound API rate limiting + quotas per tenant/user (e.g. at the gateway/ingress).
- [ ] **Claude gateway** throttling: concurrency caps and token/cost budgets per tenant; retries use backoff (already in `ClaudeGateway`) and respect 429/Retry-After; circuit-breaker on sustained provider errors.
- [ ] Bounded fan-out enforced in production workloads (use `app.integration.fanout.BoundedFanout` or the queue's concurrency cap) so a large parallel run (e.g. variance across many cost centres) cannot exhaust connectors/memory.
- [ ] Job queue (arq/Redis) has max in-flight, visibility timeouts, dead-letter queue, and `max_attempts` tuned per job kind; poison-message handling verified.
- [ ] Connector-side rate limits respected per downstream (bank/market-data/ERP); graceful degradation when a connector is throttled.
- [ ] Load test at expected peak × headroom; backpressure verified (no unbounded queue growth, no double-execution under retry).

## 6. Guardrails & human-in-the-loop — **Blocking** (C)

- [ ] Default-deny verified in production config: every consequential action is held until an explicit approval record is granted.
- [ ] Risk/compliance pre-execution gates mandatory for trade / bind / lend / filing (e.g. pre-trade risk gate, accumulation gate, KYC/sanctions, model-validation, underwriting DSR/LTV) — fail-closed on missing data.
- [ ] Approval queue UI is reachable, paged, and SLA-monitored; stale approvals alert.
- [ ] Reject path tested; rejected actions never execute and are audited.
- [ ] Evals gate: a subagent only earns reduced oversight after measured accuracy on a golden dataset; autonomy changes are change-controlled.

## 7. Observability & operations

- [ ] Per-agent run tracing wired (`app.observability`): every agent run emits a trace span (token/cost/latency) and an `agent.run` audit event with `correlation_id`. Spans exported to the APM/OTel backend.
- [ ] Cost/latency dashboards per agent + per tenant; budget alerts on token spend.
- [ ] Structured logs with correlation IDs; PII redaction in logs and traces.
- [ ] Metrics + alerts: API error rate/latency, queue depth/age, approval-queue age, job failure/retry rate, connector error rate, provider 429s.
- [ ] On-call rotation, runbooks, and SLOs defined; synthetic checks on `/health` and a canary agent run.

## 8. Security review

- [ ] Threat model reviewed for prompt injection / tool-abuse: model output can **propose** but never **execute** a consequential action outside the guardrail (the audit's no-bypass test enforces this in CI).
- [ ] Dependency scan (pip-audit / npm audit) clean or risk-accepted; images pinned and scanned.
- [ ] Pen test / security review completed and findings remediated.
- [ ] Input validation on every endpoint (Pydantic models); output encoding in the UI; CORS locked to known origins; security headers set.
- [ ] Least-privilege IAM for compute, DB, queue, vault, and each connector.

## 9. Compliance & data governance

- [ ] Data residency and retention policies enforced per jurisdiction.
- [ ] Audit/regulatory export path implemented and verified (who/what/why, model version + prompt per decision).
- [ ] Right-to-erasure / data-subject requests handled without breaking the immutable audit (segregate PII from the immutable ledger).
- [ ] Model version + prompt recorded on every model-driven decision for explainability.

---

## Sign-off

| Area | Owner | Status | Date |
|------|-------|--------|------|
| Secrets & vault | | ☐ | |
| RBAC / SSO | | ☐ | |
| DB & migrations | | ☐ | |
| Backups & DR | | ☐ | |
| Rate limits | | ☐ | |
| Guardrails / HITL (C) | | ☐ | |
| Observability | | ☐ | |
| Security review | | ☐ | |
| Compliance | | ☐ | |

Release approved by (Eng + Risk + Compliance): ______________________  Date: __________
