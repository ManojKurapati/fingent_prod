# Financial Services Agents — Build Context

## Architecture Overview

Each of the twelve business **groups** maps to exactly one top-level **orchestrator agent**. An orchestrator owns a mandate, decomposes incoming work into the responsibilities defined for its group, and dispatches them to **subagents** — narrow, tool-using workers that each own a clustered slice of the group's responsibilities. The orchestrator is the only entity that talks to the outside world (other agents, the human, the audit log); subagents are internal and addressable only through their parent. This keeps the blast radius of any single agent small and makes every action attributable to a named role — non-negotiable in a regulated environment.

Orchestration per group is one of three shapes, chosen by **data dependency**, not by taste. *Sequential* when step N consumes step N-1's output or when a step is a mandatory gate (a risk limit check must clear before a trade is routed). *Parallel* when subagents cover independent surfaces (five sector research workers, or screening a customer against five sanctions lists at once). *Hybrid* — the common real-world case — runs an independent fan-out, joins the results, then drives a dependent sequential tail (research many names in parallel → size the portfolio → pass risk gate → execute). We mark each group explicitly below and justify it.

This maps cleanly onto the **FastAPI** backend. Short, deterministic chains run inside a single `async def` endpoint, awaiting each subagent coroutine. Anything with parallel fan-out or long-running work (modelling, backtests, document diligence, reconciliations) is *not* run in the request — the endpoint enqueues a **job** onto a background worker queue (Celery/RQ/Arq over Redis, or FastAPI `BackgroundTasks` for the lightweight cases), returns a `job_id` immediately, and workers fan out with `asyncio.gather` or a worker pool. Parallel subagents are independent worker tasks; the orchestrator's join step is a barrier that waits for all children to report before the sequential tail proceeds.

Progress streams back to **React** over **SSE** (`text/event-stream` for one-way progress: "3 of 7 names researched", "risk gate: PASS") or **websockets** where the human needs to push back into a running job (approve, reject, amend). The React layer is built around per-agent **dashboards** (live job state, subagent timeline, intermediate artifacts) and **human-in-the-loop approval surfaces** — the points where a person must click before the agent crosses a consequential boundary (commit capital, bind risk, lend, file externally).

**Shared services** sit beneath all twelve agents and are called, never reimplemented: an **LLM gateway** (model routing, prompt/version pinning, token + cost metering, PII redaction); a **market-data / connector layer** (prices, reference data, CRM, custodians, regulators, exchanges — one mock-able interface per external system); a **vector store** for agent memory and retrieval (prior deals, research notes, client history, policy corpora); a **risk / compliance guardrail layer** exposed as callable gates; and an append-only **audit log** that records every subagent decision, prompt, tool call, and human approval.

The load-bearing rule: **in financial services, risk and compliance checks are mandatory gates, not advisory steps.** Any agent action that commits capital, binds insurance risk, extends credit, moves client assets, or files/communicates externally MUST pass the relevant guardrail gate first, and a *deny* halts the flow hard. Gates are sequential by construction even when everything around them is parallel.

---

## 1. Investment Banking Agent

**Mandate:** Originate, structure, and execute capital-raising and strategic-advisory mandates (M&A, ECM, DCM, leveraged finance, restructuring) end-to-end.

**Subagents:**
- `coverage_origination` — maintain sector expertise and client/prospect maps, generate proactive strategic ideas, track sector M&A and valuation trends, own primary client relationships and mandate origination, run pitch/beauty-parade preparation.
- `modeling_diligence` — build three-statement/DCF/LBO/comps and precedent-transaction analyses, run accretion/dilution and synergy work, review data rooms, contracts, and filings, maintain comp sets and intelligence trackers.
- `materials_drafting` — draft pitch books, CIMs, management and board presentations from the model and diligence outputs.
- `ma_execution` — run sell-side processes (teaser, bidder management, auction), buy-side screening and approach, negotiate price/earnouts/indemnities with counsel, coordinate antitrust/fairness/integration workstreams.
- `ecm_dcm_levfin` — structure and price IPOs/follow-ons/blocks, bonds/notes/CP, and LBO debt; build order books; liaise with rating agencies and syndicate; manage allocations, greenshoe, lock-ups, covenant flex.
- `restructuring` — analyse liquidity and covenant breaches under stress, design recap/debt-exchange/A&E solutions, negotiate with creditor committees, prepare feasibility and valuation for plans of reorganisation.

**Orchestration:** Hybrid. Origination feeds a mandate; then `modeling_diligence` must complete before `materials_drafting` and any execution subagent can act, because every deck and term sheet is downstream of the model. Within execution, `ma_execution`, `ecm_dcm_levfin`, and `restructuring` are mutually exclusive per mandate (selected by deal type), so only one runs — but its internal workstreams (diligence, drafting, negotiation) fan out in parallel.

**Execution flow:**
1. `coverage_origination` → qualified mandate.
2. `modeling_diligence` (financials) ∥ data-room review → valuation pack.
3. Join → `materials_drafting` (pitch/CIM/board) and selected execution subagent (`ma_execution` | `ecm_dcm_levfin` | `restructuring`) run in parallel.
4. **Compliance gate** (conflicts check, MNPI/wall-crossing, engagement-letter review) before any client-facing send or market launch.

**FastAPI:** `POST /ib/mandates` creates a deal and enqueues origination. `POST /ib/mandates/{id}/diligence` enqueues the modeling job (long-running → worker). `GET /ib/mandates/{id}/stream` (SSE) streams subagent progress. `POST /ib/mandates/{id}/execute` requires a cleared compliance gate token in the request.

**React:** Deal pipeline board; per-mandate workspace with live model artifacts, draftable deck preview, and a **wall-crossing / conflicts approval modal** that blocks the "send to client" and "launch" buttons until compliance signs off.

---

## 2. Sales & Trading / Markets Agent

**Mandate:** Price, quote, distribute, and execute trades across asset classes while continuously managing desk risk and client flow.

**Subagents:**
- `sales_coverage` — cover institutional accounts, distribute ideas/axes/inventory, translate client needs into orders, track wallet share and flow.
- `pricing_quoting` — trader/market-maker pricing: quote two-way prices, set quote width and skew from volatility and inventory, watch for toxic/adverse-selection flow.
- `quant_signals` — design, backtest, and validate systematic strategies; monitor live-vs-backtest performance; flag regime breaks; tune TCA/slippage assumptions.
- `structuring` — design bespoke structured/derivative payoffs, price embedded optionality, document term sheets, decompose into hedgeable components, assess capital/accounting treatment.
- `execution_algo` — select/configure VWAP/TWAP/IS algos, route across venues and dark pools, monitor fills vs benchmark, produce TCA.
- `risk_hedging` — mark the book, manage delta/vega/rate exposures in real time, rebalance inventory to neutral, enforce desk risk limits.

**Orchestration:** Hybrid with a hard sequential gate. An order is routed only after a **pre-trade risk check** clears (limits, inventory, suitability) — risk-before-execution is the canonical sequential dependency. Around that gate, `sales_coverage`, `pricing_quoting`, and `quant_signals` run in parallel continuously as independent feeds; `risk_hedging` runs concurrently post-fill to rebalance.

**Execution flow:**
1. Client request ∥ live signals (`sales_coverage`, `pricing_quoting`, `quant_signals` stream in parallel).
2. Order formed → **pre-trade risk gate** (`risk_hedging` limit + suitability check) — MANDATORY.
3. Gate PASS → `execution_algo` routes and works the order.
4. Post-fill: `risk_hedging` re-hedges, books P&L; `execution_algo` produces TCA.

**FastAPI:** `POST /markets/orders` validates, calls the pre-trade risk gate synchronously (must return PASS), then dispatches `execution_algo` as a worker task. `GET /markets/orders/{id}/fills` (SSE) streams fills and slippage. `WS /markets/desk` pushes live quotes and risk metrics. A `kill_switch` endpoint halts all execution workers.

**React:** Live desk blotter, quote/skew panel, risk heatmap (greeks vs limits), and a **limit-breach interrupt** that pauses order routing and demands trader/risk override before continuing.

---

## 3. Asset & Investment Management Agent

**Mandate:** Research, allocate, and manage portfolios to deliver mandate-compliant, risk-adjusted returns.

**Subagents:**
- `macro_strategy` — economist/strategist: produce growth/inflation/rates/policy forecasts, develop themes, track central banks and data, brief the committee.
- `asset_allocation` — multi-asset strategist: strategic/tactical allocation frameworks, macro-to-tilt translation, cross-asset correlation and stress models, model portfolios, drift monitoring.
- `buyside_research` — analysts: generate recommendations with targets and conviction, build proprietary models, run primary research, monitor holdings for thesis-breaking events. (Fans out per name/sector.)
- `portfolio_construction` — PM/fund manager/CIO logic: construct and rebalance to mandate/benchmark/risk budget, buy/sell/hold decisions, position sizing, mandate/limit/liquidity compliance, performance attribution.
- `buyside_execution` — dealing desk: best execution, liquidity sourcing, broker/venue/algo selection, order timing, market colour to PMs, commission/TCA.

**Orchestration:** Hybrid. `macro_strategy` → `asset_allocation` is sequential (allocation consumes the house macro view). `buyside_research` is a parallel fan-out across the coverage universe (independent names). Both streams join at `portfolio_construction`, which is the sequential decision point; orders then pass a **mandate/risk gate** before `buyside_execution`.

**Execution flow:**
1. `macro_strategy` → house view → `asset_allocation` sets target tilts.
2. ∥ `buyside_research` fans out across N names → recommendations.
3. Join → `portfolio_construction` builds target portfolio + attribution.
4. **Mandate & risk gate** (limits, liquidity, suitability) — MANDATORY.
5. Gate PASS → `buyside_execution` works orders, returns TCA.

**FastAPI:** `POST /aim/research/run` enqueues a fan-out research job (worker pool, one task per name). `GET /aim/research/{job_id}/stream` (SSE) streams "k of N complete". `POST /aim/portfolios/{id}/rebalance` runs construction, hits the gate, then dispatches execution.

**React:** Research coverage grid (live fan-out progress), proposed-rebalance diff (current vs target weights), attribution charts, and a **PM approval gate** on the trade list before execution.

---

## 4. Private Markets Agent

**Mandate:** Source, underwrite, and steward illiquid equity, credit, and real-asset investments across their full lifecycle.

**Subagents:**
- `origination_pipeline` — build and manage proprietary pipeline, cultivate banker/broker relationships, run outbound campaigns, screen inbound against thesis, track sourcing metrics, hand off qualified deals.
- `pe_vc_underwriting` — buyout/growth/venture diligence: LBO models, founder/PMF/TAM/moat assessment, structuring and term-sheet negotiation, IC memos.
- `credit_underwriting` — direct lending: model cash flows/leverage/covenant headroom under downside, structure terms/pricing/security, credit diligence, IC memos with ratings.
- `realasset_underwriting` — real estate and infrastructure: cap-rate/IRR/cash-flow and concession/availability/demand models, market/tenant/lease/regulatory/construction diligence, project-finance structuring.
- `fund_of_funds` — GP selection and manager due diligence, vintage/strategy/geography diversification, commitment/fee/co-invest negotiation, capital-call and distribution pacing.
- `portfolio_stewardship` — board support and value-creation plans, covenant and KPI/ESG monitoring, early-warning signals, exit/refi/disposition execution.

**Orchestration:** Hybrid. `origination_pipeline` runs continuously and independently. Once a deal qualifies, exactly one underwriting subagent runs (selected by asset class), and its diligence workstreams fan out in parallel. Underwriting → **IC approval gate** (mandatory human decision) is strictly sequential — no capital is committed before the investment committee signs. Post-close, `portfolio_stewardship` runs as an independent long-lived loop.

**Execution flow:**
1. `origination_pipeline` (continuous) → qualified deal.
2. Routed to `pe_vc_underwriting` | `credit_underwriting` | `realasset_underwriting` | `fund_of_funds`; diligence subtasks fan out in parallel.
3. Join → IC memo → **Investment Committee approval gate** (human) — MANDATORY.
4. Gate APPROVE → close; `portfolio_stewardship` begins monitoring loop.

**FastAPI:** `POST /pm/deals` (pipeline intake). `POST /pm/deals/{id}/underwrite` enqueues a long diligence job. `GET /pm/deals/{id}/stream` (SSE). `POST /pm/deals/{id}/ic-decision` records the human IC vote and unlocks close. `POST /pm/portfolio/{id}/monitor` schedules recurring stewardship via the cron/scheduler.

**React:** Pipeline funnel, deal underwriting workspace with model + diligence tabs, **IC memo review-and-vote screen** (approve/decline/conditions), and a portfolio-monitoring dashboard with KPI/covenant alerts.

---

## 5. Wealth Management & Private Banking Agent

**Mandate:** Advise individuals and families on growing, protecting, and transferring wealth, and deliver bespoke banking and discretionary portfolio management.

**Subagents:**
- `financial_planning` — comprehensive plans (cash flow, goals, protection), retirement and savings projections, tax-wrapper/pension advice, insurance/education/major-purchase modelling, life-event updates, spend/save/risk trade-offs.
- `investment_advice` — investment counsellor: translate house view to client-specific allocation and product selection, present outlooks, tailor advisory/discretionary mandates.
- `discretionary_pm` — client portfolio manager: manage discretionary books within client constraints, tax-loss harvesting, concentration/preference customisation, mandate/suitability/liquidity compliance, client-friendly reporting.
- `private_banking` — relationship manager: HNW/UHNW primary contact, Lombard loans/mortgages/credit against assets, orchestrate trust/family-office specialists, anticipate liquidity needs.
- `client_onboarding_kyc` — onboard new clients, uphold KYC, suitability, and risk standards.

**Orchestration:** Hybrid, suitability-gated. `client_onboarding_kyc` is the sequential entry gate — no advice or discretionary action occurs before KYC/suitability clears. After onboarding, `financial_planning` and `investment_advice` can run in parallel (plan and allocation inform each other but can be drafted concurrently then reconciled). `discretionary_pm` and `private_banking` actions each pass a **suitability gate** before any portfolio change or credit extension.

**Execution flow:**
1. `client_onboarding_kyc` → **KYC/suitability gate** (MANDATORY) → activated client.
2. ∥ `financial_planning` + `investment_advice` → reconciled plan + target allocation.
3. `discretionary_pm` proposes changes → **suitability gate** → implement; or `private_banking` proposes credit → suitability + credit gate.

**FastAPI:** `POST /wealth/clients` runs onboarding/KYC. `POST /wealth/clients/{id}/plan` builds plan + advice (parallel workers). `POST /wealth/clients/{id}/rebalance` and `POST /wealth/clients/{id}/credit` each require a suitability-gate token.

**React:** Client 360 view, goal-based planning visualiser, proposed-portfolio diff, and a **suitability sign-off panel** advisors must clear before any trade or Lombard facility is booked.

---

## 6. Retail & Commercial Banking Agent

**Mandate:** Serve individuals and businesses with deposits, lending, and credit at scale while controlling risk on every facility.

**Subagents:**
- `branch_ops` — branch operations, staffing, service standards, sales targets, cash-handling/security/audit controls, complaint and retention handling.
- `personal_banking` — open accounts and onboard retail customers, cross-sell cards/loans/savings/digital, basic credit eligibility, servicing/disputes, referrals to mortgage/wealth/business.
- `commercial_rm` — manage business client portfolios, structure working-capital/term/trade-finance, cross-sell treasury/cash-management, annual facility reviews, originate clients.
- `credit_analysis` — analyse statements/cash flow/repayment capacity, assign risk ratings, recommend limits and pricing, prepare credit memos, monitor exposures for breach/deterioration.
- `loan_origination` — guide product selection, collect docs and pre-qualify, explain rates/terms, liaise applicant↔underwriter, manage pipeline, ensure lending disclosures.
- `underwriting` — evaluate applications vs credit policy/appetite, verify income/employment/assets/credit, order appraisals, compute DSR/LTV/affordability, approve/decline/counter, document for audit and secondary sale.

**Orchestration:** Sequential (lending is a strict pipeline). A loan moves origination → credit analysis → underwriting → **credit-policy/risk gate** → fund, each stage gating the next because underwriting depends on credit analysis which depends on collected documentation. `branch_ops`, `personal_banking`, and `commercial_rm` run as independent intake channels feeding the pipeline.

**Execution flow:**
1. Intake via `personal_banking` | `commercial_rm` | `branch_ops`.
2. `loan_origination` (docs, pre-qual) → `credit_analysis` (rating, limit) → `underwriting` (verify, ratios, decision).
3. **Credit-policy / risk-appetite gate** — MANDATORY.
4. Gate APPROVE → fund and book; conditions/decline returned to applicant with rationale.

**FastAPI:** `POST /banking/applications` starts the pipeline; each stage is a sequential worker step writing back status. `GET /banking/applications/{id}/stream` (SSE) shows stage progression. `POST /banking/applications/{id}/decision` records the underwriting decision behind the credit gate.

**React:** Application pipeline kanban (origination → analysis → underwriting → funded), credit-memo viewer with computed ratios, and an **underwriter decision panel** (approve/decline/counter with conditions) that is the human gate.

---

## 7. Insurance Agent

**Mandate:** Price, underwrite, and manage risk transfer across the insurance lifecycle from policy inception to claim settlement.

**Subagents:**
- `actuarial` — calibrate pricing models from loss/exposure data, set IBNR and outstanding reserves and certify adequacy, compute capital (Solvency II SCR/economic), run balance-sheet stress, produce experience studies, sign actuarial opinions.
- `cat_modelling` — run vendor/in-house cat models, quantify PML/AAL/EP curves, geocode and cleanse exposure, build bespoke scenarios for emerging perils, advise accumulation limits by region/peril.
- `underwriting` — assess submissions vs appetite (accept/decline/terms), set premiums/deductibles/limits, negotiate with brokers, structure facultative placements, monitor accumulation and loss ratios.
- `claims` — triage and investigate claims, verify coverage/liability, reserve and adjust claim values, negotiate settlements within authority, coordinate adjusters/counsel, track leakage and escalate fraud.
- `reinsurance` — analyse cession/recovery, model retentions and structure QS/XoL/stop-loss, prepare renewal submissions, compute recoverables and reinsurer credit exposure, reconcile balances.
- `product` — define propositions/segments, coordinate regulatory filing of wordings/rates/rules, run profitability and competitiveness analysis, align teams, monitor in-force KPIs.

**Orchestration:** Hybrid. Underwriting depends sequentially on actuarial rates and cat-accumulation outputs — `actuarial` ∥ `cat_modelling` fan out first, join, then `underwriting` decides against a **risk-appetite / accumulation gate** before binding. `claims` runs as an independent post-bind lifecycle loop. `reinsurance` and `product` run in parallel as portfolio-level functions feeding back into appetite.

**Execution flow:**
1. Submission in → `actuarial` (rate) ∥ `cat_modelling` (accumulation) run in parallel.
2. Join → `underwriting` decision → **appetite/accumulation gate** (MANDATORY) → bind/decline/terms.
3. Post-bind loop: `claims` on FNOL; `reinsurance` and `product` continuously optimise the book.

**FastAPI:** `POST /insurance/submissions` enqueues parallel actuarial + cat jobs (workers). `GET /insurance/submissions/{id}/stream` (SSE). `POST /insurance/submissions/{id}/bind` requires the accumulation-gate token. `POST /insurance/claims` opens the claims lifecycle.

**React:** Submission workbench (rate + accumulation panels), **bind-authority approval** (block "bind" until within appetite), claims triage queue, and a portfolio accumulation/loss-ratio dashboard.

---

## 8. Risk Management Agent

**Mandate:** Identify, measure, and govern financial and non-financial risk to keep enterprise exposure within board-approved appetite.

**Subagents:**
- `market_risk` — VaR/ES/greeks across books, daily P&L attribution and limit-breach investigation, stress/scenario analysis, intraday limit monitoring, validate market data and risk-factor mappings.
- `credit_risk` — counterparty creditworthiness via PD/LGD, set/monitor limits and PFE, run credit-approval workflow, track concentration/migration/default, compute IFRS 9/CECL ECL.
- `operational_risk` — maintain risk taxonomy/RCSA/loss database, KRIs, loss-event root-cause, new-product/outsourcing assessment, op-risk capital and incident trends.
- `liquidity_risk` — monitor LCR/NSFR/survival horizons, cash-flow projections and liquidity stress, contingency funding plan, early-warning and concentration limits, HQLA buffer optimisation.
- `model_validation` — independently validate pricing/risk/capital models, benchmark and back-test, maintain model inventory/tiering, document limitations, trigger revalidation on drift.
- `erm_aggregation` — consolidate market/credit/op/liquidity into firm-wide view, own risk-appetite statement and aggregate dashboard, run enterprise stress / ICAAP/ILAAP, horizon-scan emerging risk.

**Orchestration:** Parallel fan-out into a sequential aggregation tail. The four risk-type subagents (`market_risk`, `credit_risk`, `operational_risk`, `liquidity_risk`) compute independently and concurrently against the same position snapshot; `model_validation` runs alongside as an independent assurance check. `erm_aggregation` is the join/barrier — it cannot run until all measures report, then consolidates and tests against appetite sequentially.

**Execution flow:**
1. Position snapshot → fan out: `market_risk` ∥ `credit_risk` ∥ `operational_risk` ∥ `liquidity_risk` ∥ `model_validation`.
2. Barrier (await all) → `erm_aggregation` consolidates firm-wide view + enterprise stress.
3. Breach detection → escalation to CRO/risk committee (human) with limit-vs-exposure detail.

**FastAPI:** `POST /risk/run` enqueues the parallel risk fan-out (worker pool); `erm_aggregation` is a dependent task that joins on all children. `GET /risk/run/{job_id}/stream` (SSE) streams per-measure completion. This agent also exposes the **shared guardrail gate endpoints** (`POST /risk/gate/pre-trade`, `/risk/gate/limit-check`) that other agents call.

**React:** Enterprise risk dashboard (appetite vs current per risk type), breach alert feed, stress-scenario explorer, and a **CRO escalation panel** for breach acknowledgement and limit-override approvals.

---

## 9. Compliance, Legal & Financial Crime Agent

**Mandate:** Keep the firm within legal and regulatory bounds and defend it against money laundering, fraud, and sanctions exposure.

**Subagents:**
- `compliance_monitoring` — CCO framework and annual risk assessment, second-line control testing, comms/PA-dealing/marketing review, incident logging and closure, advisory to business, registers (gifts/COI/OBA).
- `regulatory_affairs` — horizon-scan rule changes and assess applicability, coordinate filings/returns/licences, draft consultation responses and handle exams, translate obligations into policy, maintain regulatory inventory.
- `aml_kyc` — CDD/EDD at onboarding and periodic review, verify beneficial ownership/source of funds/wealth, assign and refresh risk ratings, clear remediation backlogs, maintain audit-ready records.
- `fraud_investigation` — investigate AML/fraud alerts, reconstruct transaction flows and gather evidence, file SARs/STRs, recommend restrictions/exits/law-enforcement liaison, feed patterns back to detection.
- `sanctions_screening` — screen customers/counterparties/transactions vs OFAC/UN/EU/local lists, disposition hits (true vs false positive), tune fuzzy-match thresholds, block/freeze/reject prohibited items, manage list updates.
- `legal_counsel` — draft/negotiate ISDAs/GMRAs/loan docs, advise on enforceability/netting/collateral, manage external counsel and litigation, review new business for legal risk, give regulatory-interpretation opinions.

**Orchestration:** Hybrid, and this agent is the firm's gate-of-record. Onboarding screening runs `aml_kyc` ∥ `sanctions_screening` in parallel (independent checks), then a sequential disposition: any hit routes to `fraud_investigation` / sanctions disposition before clearance. `compliance_monitoring`, `regulatory_affairs`, and `legal_counsel` operate as independent continuous functions. Crucially, this agent **publishes the compliance-gate API every other agent must call** before client-facing, market, or filing actions.

**Execution flow:**
1. Onboarding/transaction → `aml_kyc` ∥ `sanctions_screening` (parallel).
2. Clear → PASS; any hit → sequential `fraud_investigation` / sanctions disposition → SAR filing or block.
3. Continuous: `compliance_monitoring`, `regulatory_affairs`, `legal_counsel`.
4. Serves `POST /compliance/gate/*` to all other agents.

**FastAPI:** `POST /compliance/screen` runs parallel AML + sanctions workers, returns a clearance token or routes to investigation. `POST /compliance/gate/check` is the **synchronous gate** other agents call (returns PASS/HOLD/DENY). `POST /compliance/sar` files a suspicious-activity report through the connector layer.

**React:** Alert and case-management queue, sanctions hit-disposition workbench (true/false-positive), KYC remediation tracker, and a **gate-decision audit trail** view showing every PASS/DENY issued to other agents.

---

## 10. Operations (Middle & Back Office) Agent

**Mandate:** Turn front-office trade captures into accurate, confirmed, settled positions and reconciled records.

**Subagents:**
- `trade_support` — validate and enrich captures, resolve front-to-downstream booking errors, affirm/confirm with counterparties, manage lifecycle events (amend/novate/cancel), resolve trade breaks, produce intraday position reports.
- `settlements` — instruct and monitor cash/securities settlement across custodians/CSDs/CCPs, manage fails and buy-ins, reconcile nostro/depot for DvP, process margin movements, handle give-ups/allocations.
- `reconciliations` — automated/manual recs across cash/positions/trades, investigate/categorise/age breaks, drive resolution, maintain control reports, surface recurring patterns.
- `fund_accounting` — daily/periodic NAV with pricing and accruals, book income/expenses/fees/corporate-actions to the ledger, reconcile to custodian/administrator, prepare statements, validate NAV vs tolerance.
- `custody_ops` — safekeeping and holdings records with sub-custodians, transfers/deliveries/account openings, network monitoring, income collection/tax reclaim/proxy voting, position reconciliation.
- `collateral_mgmt` — calculate/issue margin calls (CSA/GMRA/cleared), agree movements and resolve disputes, manage eligibility/haircuts/substitutions, monitor inventory/concentration/rehypothecation, reconcile pledged assets.

**Orchestration:** Sequential pipeline with a parallel reconciliation layer. The trade lifecycle is strictly ordered: `trade_support` (confirm) → `settlements` (settle) — you cannot settle an unconfirmed trade. `reconciliations`, `custody_ops`, `fund_accounting`, and `collateral_mgmt` then run in parallel against settled records (independent reconciliation surfaces), with breaks routed back up to the relevant stage.

**Execution flow:**
1. Trade capture → `trade_support` validates and confirms.
2. → `settlements` instructs and monitors to settlement (fails routed back).
3. On settled records, fan out: `reconciliations` ∥ `fund_accounting` (NAV) ∥ `custody_ops` ∥ `collateral_mgmt`.
4. Breaks → categorised, aged, routed back to source stage; aged items escalated.

**FastAPI:** `POST /ops/trades/{id}/process` runs the sequential confirm→settle chain (workers, status per stage). `POST /ops/recon/run` enqueues parallel reconciliation workers nightly via the scheduler. `GET /ops/breaks/stream` (SSE) streams new and aged breaks.

**React:** Trade lifecycle status board, settlement-fails queue, reconciliation break dashboard (by age/category), NAV validation panel, and a **break-resolution workspace** for analyst action on escalated items.

---

## 11. Quantitative, Data & Technology Agent

**Mandate:** Build the models, research, and systematic strategies that turn financial data and mathematics into pricing, risk, and trading capability.

**Subagents:**
- `quant_pricing` — implement pricing/valuation models for derivatives and structured products, compute greeks and ensure front-office/risk consistency, calibrate to market quotes and maintain vol surfaces/curves, support traders with ad hoc analytics, test and document code.
- `quant_research` — formulate and test alpha hypotheses with statistical/ML methods, source/clean/engineer features from market/fundamental/alt data, backtest with realistic costs, publish findings, investigate decay/overfitting via out-of-sample.
- `risk_model_dev` — develop PD/LGD/VaR/economic-capital models, translate IRB/FRTB/IFRS 9 methodologies, build calibration pipelines, document for validation, recalibrate as data/regulation evolve.
- `data_science` — predictive/classification models for churn/default/fraud, feature pipelines from structured/unstructured data, communicate results with visualisation, deploy and monitor for drift, run experiments/A-B tests.
- `financial_engineering` — design bespoke products/payoffs, build cash-flow and pricing engines for exotics, engineer hedging/replication, bridge theory and implementation, assess risk/capital/accounting.
- `systematic_dev` — code/test/deploy automated strategies and execution algos, optimise routing/scheduling/microstructure logic, build low-latency fault-tolerant infra, monitor live performance and kill-switches, post-trade analysis.

**Orchestration:** Parallel by default, with a mandatory **model-validation gate** before production. The six subagents pursue largely independent workstreams and fan out in parallel. The non-negotiable sequential dependency: any model from `quant_pricing`, `risk_model_dev`, or `data_science`, and any strategy from `quant_research`/`systematic_dev`, must clear independent validation (Risk Agent's `model_validation`) before deployment. Research → validation → production is strictly ordered.

**Execution flow:**
1. Parallel workstreams: `quant_pricing` ∥ `quant_research` ∥ `risk_model_dev` ∥ `data_science` ∥ `financial_engineering` ∥ `systematic_dev`.
2. Candidate model/strategy → **independent model-validation gate** (Risk Agent) — MANDATORY.
3. Gate APPROVE → deploy to production library / live trading with monitoring + kill-switch.

**FastAPI:** `POST /quant/jobs` enqueues backtests/calibrations (long-running worker pool, GPU/compute where needed). `GET /quant/jobs/{job_id}/stream` (SSE) streams backtest progress and metrics. `POST /quant/models/{id}/promote` is blocked unless a validation token from the Risk Agent is present.

**React:** Model/strategy registry with lifecycle state (draft → validating → live), backtest results explorer, drift-monitoring dashboard, and a **promote-to-production gate** wired to the validation sign-off.

---

## 12. Product, Strategy & Client Agent

**Mandate:** Define financial products, set pricing, and own the commercial relationship across onboarding, service, and distribution.

**Subagents:**
- `product_management` — own roadmap and prioritisation, write requirements/user stories, coordinate eng/design/compliance delivery, define and analyse success metrics, run discovery, manage backlog and go-to-market readiness.
- `pricing` — build pricing models and fee schedules (competitiveness/margin/risk), analyse elasticity and win/loss and competitor benchmarking, set deal pricing and discount approvals, monitor realised margin, model revenue impact of changes.
- `client_onboarding` — guide account opening/documentation/system setup, coordinate KYC and legal execution and entitlements, track milestones and remove blockers, configure connectivity and SSIs, hand over activated clients.
- `client_services` — institutional primary contact, resolve cross-functional service issues, service reviews and cross-sell/retention, channel feedback into product/ops, maintain relationship plans and account-health scoring.
- `sales_distribution` — own pipeline and revenue targets across direct/intermediated channels, develop partnerships/broker/platform relationships, run GTM campaigns, negotiate and close deals, forecast and report conversion.

**Orchestration:** Hybrid. Product definition is sequential at the front: `product_management` (discovery/requirements) → `pricing` (models the economics) → **compliance/regulatory filing gate** before launch. Post-launch, the commercial loop runs in parallel: `sales_distribution`, `client_onboarding`, and `client_services` operate concurrently per client, with `client_onboarding` internally gated by KYC before activation.

**Execution flow:**
1. `product_management` discovery → requirements → `pricing` economics.
2. → **compliance / regulatory-filing gate** (wording/rate filing where required) — MANDATORY before launch.
3. Launch → parallel commercial loop: `sales_distribution` (pipeline) ∥ `client_onboarding` (KYC-gated activation) ∥ `client_services` (retention/feedback).
4. Feedback and metrics loop back to `product_management`.

**FastAPI:** `POST /product/initiatives` runs the discovery→pricing chain. `POST /product/initiatives/{id}/launch` requires the compliance/filing gate token. `POST /clients/onboard` runs onboarding behind the KYC gate. `GET /product/initiatives/{id}/metrics/stream` (SSE) streams adoption/retention.

**React:** Product roadmap and backlog board, pricing-scenario modeller (revenue impact preview), onboarding milestone tracker, client-health dashboard, and a **launch-approval gate** that blocks go-live until filings/compliance clear.

---

## Cross-Agent Orchestration & Guardrails

The twelve agents are not islands; they chain into firm-wide value flows. The canonical investment chain is **Asset/Investment Management (research → portfolio) → Sales & Trading (execution) → Operations (confirm → settle → reconcile)**, with **Risk Management** supplying the pre-trade gate between portfolio and execution and **Compliance** supplying the conduct/suitability gate. The capital-markets chain is **Investment Banking (structure) → Compliance (wall-crossing/conflicts) → Sales & Trading (distribute/syndicate) → Operations (settle)**. The lending chain is **Retail/Commercial Banking (origination → underwriting) → Risk (credit gate) → Operations (booking)**. Private Markets chains **origination → underwriting → IC gate → Operations/Fund Accounting** for fund servicing. In every chain, **Quant/Data/Technology** supplies the models and **Product/Strategy/Client** owns the wrapper and the client relationship.

Cross-agent calls go through the orchestrator layer over the same FastAPI surface: one agent's tail step calls another agent's gate or intake endpoint, passing a correlation/trace ID so the **audit log** stitches the full chain. Long chains run as a saga of background jobs — each agent's worker completes, emits an event, and the next agent's job is triggered; React subscribes to the chain-level SSE/websocket stream to render end-to-end progress across agents.

The guardrails are absolute and architectural. **No agent may commit capital, bind insurance risk, extend credit, move client assets, or file/communicate externally without first passing the mandatory gate(s):** a **Risk gate** (limits, appetite, suitability, model-validation) and/or a **Compliance gate** (KYC, sanctions, conflicts/wall-crossing, regulatory filing). Gates are synchronous, fail-closed (a missing or errored gate response = DENY, never PASS), and return a signed token that the consequential endpoint requires; without the token the action endpoint refuses the request. Risk Management owns the risk gates; Compliance, Legal & Financial Crime owns the compliance gates; the model-validation gate sits in Risk and blocks Quant promotion. Every gate decision — PASS, HOLD, DENY, and any human override — is written to the append-only audit log with the prompt, inputs, model version, and approver identity, so any action in the firm is fully reconstructable for regulators.
