# Enterprise Finance Agents — Build Context

## Architecture Overview

This system models the finance organisation as **nine top-level orchestrator agents**, one per functional group. Each group file defines a set of roles and responsibilities; in the agent model, a group becomes an **orchestrator agent**, and the responsibilities cluster into **subagents** that actually do the work. The orchestrator owns intake, decomposition, dependency sequencing, error handling, and the final synthesis back to the caller. Subagents are stateless task workers that take a typed input, call tools, and emit a typed result plus an audit trace. The orchestrator decides whether its subagents run **sequentially** (output of one feeds the next), in **parallel** (independent, fan-out), or as a **hybrid** (a sequential spine with parallel stages bolted on).

Orchestration maps cleanly onto the FastAPI backend. A request to an agent hits an **async endpoint** (`POST /agents/<group>/<action>`) that validates input, creates a **job** record in Postgres, enqueues it onto a queue (Redis/RQ, Celery, or Arq), and returns a `job_id` immediately. **Background workers** pick up the job and run the orchestrator's plan. Parallel fan-out is just multiple worker tasks dispatched concurrently (`asyncio.gather` for I/O-bound LLM/API calls within one worker, or N enqueued child jobs for heavy/long-running work). Sequential steps are chained: a worker completes stage 1, persists its output, then enqueues stage 2. Hybrid plans are a DAG the orchestrator walks, releasing a stage only when its dependencies are `complete`.

Progress streams back to React over **SSE** (`GET /jobs/{job_id}/events`) or websockets. Each subagent publishes lifecycle events (`queued → running → tool_call → needs_approval → complete/failed`) to a per-job channel; the React client subscribes and renders live progress. Long parallel fan-outs (e.g. 400 account reconciliations) stream incremental completion counts rather than waiting for the whole batch.

The React frontend is organised as **per-agent dashboards** plus a shared **job/run inspector**. Every agent surfaces: a trigger panel, a live run view (the streaming DAG of subagents), an exceptions/queue view, and — critically — **human-in-the-loop approval gates**. Any action that posts to the ledger, moves cash, files externally, or changes master data renders an approval card that blocks the worker until a human approves, edits, or rejects it.

**Shared services** (consumed by every agent, owned by none):
- **LLM Gateway** — single egress for model calls (prompt templates, routing, caching, token/cost accounting, PII redaction, retries). Agents never call a model SDK directly.
- **Tool / Connector layer** — typed adapters to ERP/GL (NetSuite, SAP, Oracle), bank APIs/host-to-host, payroll, CRM, tax engines, market-data and filing systems. Each tool declares whether it is **read** or **write** (writes are gated).
- **Vector store** — agent memory: prior memos, policy docs, prior-period explanations, contracts, audit workpapers, retrieved for grounding/RAG.
- **Audit log** — append-only event store. Every tool call, LLM call, subagent input/output, and human approval is written immutably with actor, timestamp, and job lineage. This is the system of record for "who/what/why" and feeds the Internal Audit agent directly.

---

## 1. Leadership Agent

**Mandate:** Set financial direction, own capital strategy, and synthesise the outputs of all other finance agents into board-ready decisions and guidance.

**Subagents:**
- `capital-strategy` — capital structure (debt/equity/dividend) modelling, capital-allocation recommendations, financing-option trade-offs.
- `board-investor-reporting` — board packs, investor/lender narratives, guidance, risk-posture summaries.
- `budget-plan-signoff` — review and sign-off staging for annual budgets, long-range plans, and material financial commitments.
- `divisional-rollup` — translate group targets into divisional plans and consolidate divisional P&L ownership into a group view.
- `transformation-sponsor` — track and prioritise finance/AI-automation initiatives across the function.

**Orchestration: Hybrid.** This agent is primarily a **synthesiser**: `divisional-rollup` and underlying group-agent outputs (FP&A forecasts, Treasury liquidity, Tax ETR) must land **before** `capital-strategy` and `board-investor-reporting` can run — that spine is sequential. But once consolidated inputs exist, `board-investor-reporting`, `budget-plan-signoff` staging, and `transformation-sponsor` reporting are **independent and run in parallel**. Capital strategy depends on Treasury and FP&A data, so it is gated behind them.

**Execution flow:**
1. Fan-in: pull latest outputs from FP&A, Treasury, Accounting, Tax agents → `divisional-rollup` consolidates.
2. → `capital-strategy` (needs consolidated position).
3. Parallel: `board-investor-reporting` ‖ `budget-plan-signoff` ‖ `transformation-sponsor`.
4. → Human approval gate (CFO) → publish board pack / guidance.

**FastAPI:** `POST /agents/leadership/board-pack` → enqueues a fan-in job that may call other agents' endpoints internally → workers → `needs_approval` event → `POST /agents/leadership/board-pack/{job_id}/approve`. `POST /agents/leadership/capital-scenario` for ad-hoc capital modelling.

**React:** Executive cockpit — consolidated P&L/cash/risk tiles, drill-down into each source agent's run, a capital-scenario sandbox, and a CFO approval queue for board packs, budgets, and material commitments.

---

## 2. FP&A Agent

**Mandate:** Plan, forecast, and translate financial data into decision-ready analysis that steers the business.

**Subagents:**
- `data-intake` — gather and validate input data from business/ERP/CRM (owns input quality before any modelling).
- `budget-consolidation` — compile and reconcile departmental budget submissions; maintain hierarchies, accounts, allocation rules.
- `forecast-engine` — driver-based forecasts and rolling forecasts; update as actuals/assumptions change.
- `variance-analysis` — actuals-vs-plan variance, chase explanations from cost-centre owners, flag overspend early.
- `scenario-modelling` — multi-year scenario/sensitivity analysis, business cases, strategic option quantification.
- `revenue-analytics` — revenue forecasting by product/channel/segment; bookings, churn, renewals, ARR/retention KPIs.
- `reporting-packs` — management reports, dashboards, and the consolidated planning package.

**Orchestration: Hybrid.** Forecasting has a hard dependency: **`data-intake` must complete first** (a forecast needs validated actuals), and **`variance-analysis` needs actuals + plan** — so the spine `data-intake → (budget-consolidation, actuals) → forecast/variance` is sequential. But `revenue-analytics`, `scenario-modelling`, and per-cost-centre variance are **mutually independent and fan out in parallel** once inputs are loaded. `reporting-packs` is a fan-in that runs last.

**Execution flow:**
1. `data-intake` (validate, block on failures).
2. → `budget-consolidation` (consolidate submissions).
3. Parallel fan-out: `forecast-engine` ‖ `variance-analysis` (per cost centre) ‖ `revenue-analytics` ‖ `scenario-modelling`.
4. Fan-in → `reporting-packs` → stream pack to React.

**FastAPI:** `POST /agents/fpa/forecast` → enqueues job → `data-intake` worker → on success enqueues N parallel `variance-analysis` child jobs (one per cost centre) via `asyncio.gather`/queue → SSE streams per-centre completion → `reporting-packs` assembles. `POST /agents/fpa/scenario` runs the modelling subagent standalone.

**React:** Planning dashboard with forecast vs plan vs actual, a live variance grid (cost centres turning green as workers finish), a scenario sandbox with adjustable drivers, and a "request explanation" workflow that pings cost-centre owners (human-in-the-loop on variance commentary).

---

## 3. Accounting & Controllership Agent

**Mandate:** Ensure every transaction is recorded accurately and compliantly, and own the close and consolidated financial statements.

**Subagents:**
- `journal-entries` — prepare/post routine JEs, accruals, prepayments, adjusting entries across the chart of accounts.
- `reconciliations` — balance-sheet and GL account reconciliations; clear reconciling items; tie sub-ledgers to GL.
- `fixed-assets` — fixed-asset register, depreciation/amortisation, additions/disposals, sub-ledger-to-GL recon.
- `cost-inventory` — standard costs, cost-variance analysis, inventory valuation and sub-ledger recon.
- `technical-accounting` — ASC 606 / IFRS 15 interpretation, contract review, technical memos for judgemental/structured deals.
- `consolidations` — multi-entity/multi-currency consolidation, intercompany elimination, FX translation, group packages.
- `close-orchestration` — drive the close calendar, sequence sub-ledger inputs, ensure timeliness.

**Orchestration: Hybrid (sequential close spine, parallel sub-ledgers).** Sub-ledger work is **independent and parallel**: `journal-entries`, `fixed-assets`, and `cost-inventory` can all run at once. But `reconciliations` requires sub-ledgers posted, and **`consolidations` strictly requires all entity-level books closed first** — so consolidation is sequenced last. `technical-accounting` runs ahead of/in parallel where new contracts exist, feeding revenue JEs. `close-orchestration` is the controller that gates each stage.

**Execution flow:**
1. `close-orchestration` opens period.
2. Parallel: `journal-entries` ‖ `fixed-assets` ‖ `cost-inventory` ‖ `technical-accounting` (new contracts).
3. → `reconciliations` (sub-ledgers must tie to GL) — exceptions routed to humans.
4. → `consolidations` (all entities closed) → group package.
5. Human sign-off (Controller) before close locks.

**FastAPI:** `POST /agents/accounting/close/start` → creates close job → fans out sub-ledger child jobs → SSE streams a close checklist (each task → done/exception) → reconciliation exceptions raise `needs_approval` → `POST /agents/accounting/close/{job_id}/post` to commit JEs after approval. **All ledger writes are gated.**

**React:** Close cockpit — a live close calendar/checklist, reconciliation exception queue, a JE approval drawer (proposed entry + supporting evidence + LLM rationale), and a consolidation tie-out view. Nothing posts to the GL without explicit human approval.

---

## 4. Transactional / Operational Finance Agent

**Mandate:** Process the high volume of payables, receivables, billing, collections, payroll, and procurement that keeps cash and operations flowing.

**Subagents:**
- `accounts-payable` — invoice capture, 3-way match to PO/receipt, payment-run scheduling, vendor statement recon, AP aging, vendor master + fraud controls.
- `accounts-receivable` — cash application to open invoices, AR sub-ledger recon, unapplied receipts, DSO, customer master + credit limits.
- `billing` — generate invoices from contracts/usage, apply pricing/discount/tax, credit notes/rebills, dispute resolution.
- `collections` — dunning, creditworthiness assessment, payment-plan negotiation, collections forecasting, write-off recommendations.
- `payroll` — payroll runs, wage/overtime/deduction calc, tax/benefit remittance, payroll account recon.
- `procurement` — PO creation against requisitions, sourcing/negotiation, spend-vs-budget tracking, spend analytics.

**Orchestration: Parallel (with one local sequence).** These are **largely independent process streams** — AP, AR, billing, collections, payroll, and procurement run concurrently as separate worker pools, each chewing through its own queue. The only intra-stream dependency: **`billing` must produce the invoice before `accounts-receivable` and `collections` act on it** (a short sequential chain inside the O2C lane). Across lanes, everything fans out in parallel and is the heaviest user of background workers.

**Execution flow:**
- Parallel lanes: `accounts-payable` ‖ `payroll` ‖ `procurement` ‖ (O2C: `billing` → `accounts-receivable` → `collections`).
- Each lane streams exceptions (match failures, payment holds, disputes) to its own human queue.
- Payment runs and payroll disbursement hit a **mandatory cash-movement approval gate**.

**FastAPI:** Queue-driven, not request/response — `POST /agents/transactional/ap/run` enqueues a payment-run job; long-running batch workers process invoices with `asyncio` concurrency. `POST /agents/transactional/ap/{run_id}/release` requires approval before any disbursement. Webhook ingestion (`POST /agents/transactional/invoices/ingest`) feeds AP/billing queues. SSE streams batch progress (`1,240 / 1,500 invoices matched`).

**React:** Operational queues per lane — AP match-exception queue, AR cash-application review, collections worklist with suggested actions, payroll run review. The payment-run release screen is a hard approval gate showing total cash out, beneficiaries, and anomaly flags.

---

## 5. Treasury Agent

**Mandate:** Safeguard cash, liquidity, and financial risk so the organisation can always meet obligations and fund growth.

**Subagents:**
- `cash-positioning` — daily cash position across all accounts, sweeps/pooling, payment execution, bank-statement recon, fee optimisation.
- `liquidity-forecasting` — short/medium-term cash-flow forecasts, working-capital (AR/AP/inventory) analysis, stress scenarios, minimum-cash buffers, liquidity KPIs.
- `fx-hedging` — FX/interest/commodity exposure identification, hedge execution per policy, derivative valuation, hedge-effectiveness and mark-to-market reporting.
- `debt-covenants` — debt compliance, covenant monitoring, interest payments, lender reporting, support for issuances/refinancings/ratings.
- `bank-connectivity` — bank account structures, signatories, portal/TMS administration, payment-initiation controls.

**Orchestration: Sequential.** Treasury is dependency-chained: you **cannot forecast liquidity without the cash position**, and you **cannot decide FX/hedging actions or covenant headroom without the liquidity forecast**. So `cash-positioning → liquidity-forecasting → (fx-hedging, debt-covenants)` is a deliberate sequence. `bank-connectivity` is a supporting/standing service. The terminal FX-execution and any sweep/payment step hit a cash-movement gate.

**Execution flow:**
1. `cash-positioning` (consolidate balances, reconcile to bank).
2. → `liquidity-forecasting` (needs today's position + AR/AP from Transactional agent).
3. → Parallel tail: `fx-hedging` ‖ `debt-covenants` (both consume the forecast).
4. Hedge/sweep execution → cash-movement approval (Treasurer).

**FastAPI:** `POST /agents/treasury/daily-position` runs the morning sequence → SSE streams each stage → produces a liquidity dashboard payload. `POST /agents/treasury/hedge/execute` and `POST /agents/treasury/sweep` are gated write endpoints requiring approval and writing to the audit log before touching bank APIs.

**React:** Treasury dashboard — cash-position map by entity/bank/currency, liquidity forecast with stress-scenario toggles, covenant headroom gauges, and an exposure/hedge panel. Hedge and sweep execution render approval cards with policy-compliance checks.

---

## 6. Tax Agent

**Mandate:** Manage tax obligations, optimise the group's effective tax rate, and ensure compliance across every jurisdiction.

**Subagents:**
- `direct-tax-compliance` — corporate income-tax computations, returns, filing-deadline tracking, GL tax-account recon.
- `tax-provision` — current/deferred tax provision, ETR analysis, financial-statement tax disclosures.
- `indirect-tax` — VAT/GST/sales-tax returns by jurisdiction, treatment determination, input-credit recovery, ERP tax-logic config.
- `transfer-pricing` — intercompany pricing policy + documentation (master/local files), benchmarking, restructuring impact.
- `international-tax` — cross-border structuring, PE risk, withholding/treaty relief, foreign tax credits, BEPS/Pillar Two/CFC.
- `audit-defence` — manage authority queries/audits/disputes, monitor legislative change and assess impact.

**Orchestration: Hybrid.** Compliance computations are **independent by tax type** — `direct-tax-compliance`, `indirect-tax`, `transfer-pricing`, and `international-tax` fan out in **parallel** across jurisdictions. But the **`tax-provision` is a fan-in that needs all current/deferred positions assembled first** (it consumes direct + international + TP outputs to land the ETR), so it is sequenced last. `audit-defence` and legislative monitoring run as a parallel standing stream feeding all others.

**Execution flow:**
1. Parallel fan-out: `direct-tax-compliance` ‖ `indirect-tax` ‖ `transfer-pricing` ‖ `international-tax` (per jurisdiction/entity).
2. Fan-in → `tax-provision` (assemble current + deferred → ETR + disclosures).
3. Human review (Head of Tax) before filing.
4. `audit-defence` runs continuously alongside, surfacing risks.

**FastAPI:** `POST /agents/tax/provision` orchestrates the parallel computations then the provision fan-in → SSE streams per-jurisdiction completion. `POST /agents/tax/file/{return_id}` is a gated **external-filing** endpoint requiring approval and writing an immutable filing record to the audit log.

**React:** Tax workbench — provision roll-forward and ETR bridge, a jurisdiction-by-jurisdiction filing tracker with deadlines, transfer-pricing documentation status, and an approval gate on every external submission. Legislative-change alerts surface as a feed.

---

## 7. Internal Audit & Controls Agent

**Mandate:** Provide independent assurance by testing controls, evaluating risk, and protecting the integrity of financial processes.

**Subagents:**
- `audit-planning` — build the risk-based audit plan, scope engagements, design audit programs.
- `control-testing` — execute test procedures, gather evidence, document walkthroughs, identify gaps.
- `sox-controls` — maintain the SOX control matrix/narratives, test design + operating effectiveness, assess deficiency severity.
- `findings-reporting` — draft findings/recommendations, compile workpapers, assemble audit reports.
- `remediation-tracking` — track corrective actions and prior findings to closure with process owners.

**Orchestration: Sequential.** Audit is inherently ordered: **you plan, then test, then report, then track remediation** — each stage consumes the prior stage's output (`audit-planning → control-testing/sox-controls → findings-reporting → remediation-tracking`). Within the testing stage, individual control tests across processes can fan out in **parallel**, but the macro-flow is a strict sequence. This agent is also the **primary consumer of the shared audit log**, reading other agents' immutable traces as evidence — preserving independence (it observes, it does not act).

**Execution flow:**
1. `audit-planning` (risk-rank, scope).
2. → Parallel within stage: `control-testing` ‖ `sox-controls` (per control/process) — pulls evidence from the audit log.
3. → `findings-reporting` (synthesise gaps).
4. → `remediation-tracking` (assign + monitor to closure).

**FastAPI:** `POST /agents/audit/engagement` starts a sequenced engagement job → control-test child jobs fan out → SSE streams test pass/fail. Read-only access to the audit-log service is first-class here. `POST /agents/audit/findings/{id}/publish` gates report issuance behind CAE approval.

**React:** Assurance dashboard — audit plan/calendar, a control-testing grid (pass/fail/exception), SOX matrix coverage, a findings register with severity, and a remediation tracker with ageing. Process owners get a sign-off task when accepting findings.

---

## 8. Corporate Development & Strategy Agent

**Mandate:** Drive inorganic growth, evaluate transactions, and shape the company's relationship with investors.

**Subagents:**
- `pipeline-sourcing` — build/prioritise the acquisition and partnership target pipeline against strategy.
- `valuation-modelling` — acquisition valuation, accretion/dilution, synergy and deal-economics models.
- `due-diligence` — financial/commercial diligence on targets, coordinate advisors/legal/diligence workstreams.
- `deal-materials` — investment memos, board decks, deal rationale and returns presentation.
- `strategy-analysis` — market/competitor/industry analysis, entry/exit/growth cases, long-term scenario modelling.
- `investor-relations` — earnings releases, investor presentations/Q&A, analyst feedback, consensus/ownership monitoring.

**Orchestration: Hybrid.** Deal evaluation is sequential at its core — **a target must be sourced/screened before it's valued, and valuation feeds the memo** (`pipeline-sourcing → valuation-modelling → deal-materials`). But **`due-diligence` runs in parallel with `valuation-modelling`** (diligence findings refine the model iteratively), and `strategy-analysis` and `investor-relations` are **independent standing streams** that run on their own cadence (strategy continuously, IR around earnings). So it's a sequential deal spine with parallel diligence and two independent lanes.

**Execution flow:**
1. `pipeline-sourcing` (screen + prioritise).
2. → Parallel: `valuation-modelling` ‖ `due-diligence` (iterate together).
3. → `deal-materials` (board memo/returns).
4. Independent lanes: `strategy-analysis` (continuous) ‖ `investor-relations` (earnings-cadence).
5. Deal recommendation → board approval gate.

**FastAPI:** `POST /agents/corpdev/deal` spins up a deal job (valuation + diligence run concurrently) → SSE streams diligence workstream status and model versions. `POST /agents/corpdev/ir/earnings-pack` for the IR lane. External investor communications route through an approval + audit-log gate (Reg FD-style disclosure control).

**React:** Deal room per target — pipeline kanban, valuation model with adjustable assumptions, diligence checklist by workstream, and a memo/board-deck assembler. Separate IR console for earnings prep with an approval gate on anything published to the market.

---

## 9. Finance Systems & Operations Agent

**Mandate:** Run the finance platforms, govern financial data, and continuously improve how finance operates.

**Subagents:**
- `erp-administration` — configure/maintain ERP and finance apps, support tickets, enhancements/upgrades, user access + segregation-of-duties.
- `data-pipelines` — extract/cleanse/validate/reconcile financial data, build pipelines and queries, define metrics/data definitions.
- `dashboards-reporting` — build/maintain finance dashboards and reporting datasets, surface trends/anomalies.
- `process-transformation` — identify/prioritise automation opportunities, run transformation projects, map current/future-state processes, measure efficiency gains.
- `o2c-p2p-process-owner` — own end-to-end O2C/P2P design, standard procedures + controls, KPI monitoring, resolve cross-functional breakdowns.

**Orchestration: Hybrid.** Data has a clear dependency: **`data-pipelines` must land clean, reconciled data before `dashboards-reporting` can render it** — that pair is sequential and underpins every other agent's analytics. `erp-administration`, `process-transformation`, and `o2c-p2p-process-owner` are **independent, parallel** workstreams (config changes, improvement projects, and process governance don't block each other). This agent is foundational — it feeds data and platform health to all eight other agents.

**Execution flow:**
- Sequential spine: `data-pipelines` (extract → cleanse → reconcile) → `dashboards-reporting`.
- Parallel lanes: `erp-administration` ‖ `process-transformation` ‖ `o2c-p2p-process-owner`.
- Access/config changes that affect segregation-of-duties hit an approval gate (feeds Internal Audit).

**FastAPI:** `POST /agents/finops/pipeline/run` triggers ETL workers → on success enqueues dashboard refresh → SSE streams pipeline stage + row-reconciliation status. `POST /agents/finops/erp/access-change` is gated (SoD review). Scheduled jobs (cron) drive recurring pipeline runs feeding the other agents.

**React:** Operations console — data-pipeline health/freshness, reconciliation status, dashboard catalogue, transformation project board, and O2C/P2P process KPIs. Access-change and ERP-config approvals surface as gated tasks with SoD conflict warnings.

---

## Cross-Agent Orchestration

The **Leadership (CFO) agent sits above the other eight** and can invoke them as tools. Internally each group agent exposes a typed invocation contract (the same `POST /agents/<group>/<action>` endpoints plus a programmatic in-process client), so when the CFO agent assembles a board pack it calls `fpa.forecast`, `treasury.daily-position`, `tax.provision`, and `accounting.close` as child jobs, waits on their completion (fan-in via the job model), and synthesises. The same mechanism lets **any agent call another's read endpoints** — FP&A pulls actuals from Accounting; Treasury pulls AR/AP from Transactional; Internal Audit reads every agent's audit-log trace. Cross-agent calls are themselves jobs in the queue, so a CFO request transparently fans out into a tree of sub-jobs with full lineage in Postgres and the audit log.

A **single shared human-approval gate** governs every consequential write, regardless of which agent originates it. Any subagent action that **(a) posts to the ledger, (b) moves cash, or (c) files/communicates externally** must transition to `needs_approval`, halt its worker, emit an approval event over SSE, and wait. The gate is a common service: it records the proposing agent, the proposed action, supporting evidence, LLM rationale, and required approver role (Controller for GL posts, Treasurer for cash, Head of Tax for filings, CAE for findings, CFO for capital/board items). Approval, edit, or rejection is written immutably to the audit log before the worker resumes — so the entire enterprise has one consistent, auditable choke point between AI proposal and real-world financial effect.
