// Catalogue of organisations, agent groups, the agents inside each group, and the
// external portals each group connects to. Pure data — drives the Agent Catalog
// tiles and the deploy flow. Subagent names mirror the backend group definitions.

export interface Organisation {
  id: string
  name: string
  tagline: string
  icon: string
}

export interface PortalField {
  key: string
  label: string
  secret?: boolean
  placeholder?: string
}

export interface Portal {
  id: string
  name: string
  category: string
  icon: string
  fields: PortalField[]
}

export interface AgentGroup {
  id: string
  org: string
  /** Short label used in the sidebar nav. */
  navLabel: string
  /** Full title shown on tiles. */
  title: string
  icon: string
  blurb: string
  /** Subagents that make up the group (the deployable "agents"). */
  agents: string[]
  /** Plain-English outcomes a user can get from this group — "what you can do". */
  capabilities: string[]
  /** Portal ids this group depends on. */
  portals: string[]
  /** View id of the group's dashboard, when one exists. */
  page?: string
}

export const ORGANISATIONS: Organisation[] = [
  {
    id: 'enterprise',
    name: 'Enterprise Finance',
    tagline: 'The in-house finance function — close, plan, fund, comply.',
    icon: '🏛️',
  },
  {
    id: 'financial-services',
    name: 'Financial Services',
    tagline: 'Front-to-back lines of business — markets, lending, advisory.',
    icon: '📈',
  },
]

// ---- connectable portals (the systems the org already runs) ---------------

const KEY: PortalField = { key: 'apiKey', label: 'API key', secret: true, placeholder: 'sk-…' }

export const PORTALS: Portal[] = [
  {
    id: 'anthropic',
    name: 'Anthropic (Claude)',
    category: 'Model provider',
    icon: '🧠',
    fields: [{ key: 'apiKey', label: 'ANTHROPIC_API_KEY', secret: true, placeholder: 'sk-ant-…' }],
  },
  { id: 'netsuite', name: 'Oracle NetSuite', category: 'ERP / GL', icon: '📒', fields: [{ key: 'accountId', label: 'Account ID' }, KEY] },
  { id: 'sap', name: 'SAP S/4HANA', category: 'ERP / GL', icon: '🧾', fields: [{ key: 'host', label: 'Host URL' }, KEY] },
  { id: 'quickbooks', name: 'QuickBooks', category: 'ERP / GL', icon: '💚', fields: [KEY] },
  { id: 'plaid', name: 'Plaid', category: 'Banking', icon: '🏦', fields: [{ key: 'clientId', label: 'Client ID' }, { key: 'secret', label: 'Secret', secret: true }] },
  { id: 'swift', name: 'SWIFT gpi', category: 'Banking', icon: '🔁', fields: [{ key: 'bic', label: 'BIC' }, KEY] },
  { id: 'jpmaccess', name: 'J.P. Morgan Access', category: 'Banking', icon: '🏛️', fields: [KEY] },
  { id: 'bloomberg', name: 'Bloomberg Terminal', category: 'Market data', icon: '📊', fields: [KEY] },
  { id: 'refinitiv', name: 'LSEG Refinitiv', category: 'Market data', icon: '📉', fields: [KEY] },
  { id: 'factset', name: 'FactSet', category: 'Market data', icon: '🔢', fields: [KEY] },
  { id: 'salesforce', name: 'Salesforce', category: 'CRM', icon: '☁️', fields: [{ key: 'instance', label: 'Instance URL' }, KEY] },
  { id: 'sharepoint', name: 'SharePoint', category: 'Documents', icon: '📁', fields: [{ key: 'tenant', label: 'Tenant' }, KEY] },
  { id: 'snowflake', name: 'Snowflake', category: 'Data warehouse', icon: '❄️', fields: [{ key: 'account', label: 'Account' }, KEY] },
  { id: 'worldcheck', name: 'World-Check', category: 'Screening', icon: '🛡️', fields: [KEY] },
]

export const PORTALS_BY_ID: Record<string, Portal> = Object.fromEntries(PORTALS.map((p) => [p.id, p]))

// ---- agent groups ----------------------------------------------------------

export const GROUPS: AgentGroup[] = [
  // ---------------- Enterprise Finance ----------------
  {
    id: 'leadership', org: 'enterprise', navLabel: 'Leadership', title: 'Executive Cockpit', icon: '🎯', page: 'leadership',
    portals: ['anthropic', 'netsuite', 'salesforce'],
    blurb: 'Divisional roll-up, capital strategy, and board reporting.',
    capabilities: [
      'Roll every division’s P&L into one board-ready view',
      'Pressure-test capital allocation and funding strategy',
      'Draft board and investor reporting packs',
      'Sign off budgets and sponsor transformation programmes',
    ],
    agents: ['divisional-rollup', 'capital-strategy', 'board-investor-reporting', 'budget-plan-signoff', 'transformation-sponsor'],
  },
  {
    id: 'fpa', org: 'enterprise', navLabel: 'FP&A', title: 'FP&A Planning', icon: '📐', page: 'fpa',
    portals: ['anthropic', 'netsuite', 'snowflake'],
    blurb: 'Forecasts, variance, scenarios, and reporting packs.',
    capabilities: [
      'Generate driver-based forecasts across every cost centre',
      'Explain budget-vs-actual variance in plain-English commentary',
      'Model “what-if” scenarios (e.g. price moves 5%) in seconds',
      'Assemble the monthly reporting pack automatically',
    ],
    agents: ['data-intake', 'budget-consolidation', 'forecast-engine', 'revenue-analytics', 'scenario-modelling', 'reporting-packs'],
  },
  {
    id: 'accounting', org: 'enterprise', navLabel: 'Accounting', title: 'Accounting Close', icon: '📚', page: 'accounting',
    portals: ['anthropic', 'netsuite', 'sap'],
    blurb: 'Close orchestration, journals, recs, and consolidations.',
    capabilities: [
      'Orchestrate the month-end close end to end',
      'Draft and post journal entries — held for your approval',
      'Reconcile accounts and flag breaks for review',
      'Consolidate entities and handle technical accounting',
    ],
    agents: ['close-orchestration', 'journal-entries', 'fixed-assets', 'cost-inventory', 'technical-accounting', 'reconciliations', 'consolidations'],
  },
  {
    id: 'tax', org: 'enterprise', navLabel: 'Tax', title: 'Tax Workbench', icon: '🧮', page: 'tax',
    portals: ['anthropic', 'netsuite'],
    blurb: 'Provision, ETR, transfer pricing, and filings.',
    capabilities: [
      'Compute the tax provision and effective tax rate',
      'Prepare direct, indirect, and international filings',
      'Run transfer-pricing analysis and documentation',
      'Build audit-defence files before you file a return',
    ],
    agents: ['direct-tax-compliance', 'indirect-tax', 'transfer-pricing', 'international-tax', 'audit-defence', 'tax-provision', 'file-return'],
  },
  {
    id: 'treasury', org: 'enterprise', navLabel: 'Treasury', title: 'Treasury', icon: '💧', page: 'treasury',
    portals: ['anthropic', 'plaid', 'swift', 'jpmaccess'],
    blurb: 'Cash positioning, liquidity, FX hedging, bank connectivity.',
    capabilities: [
      'See your global cash position in real time',
      'Forecast liquidity and upcoming funding needs',
      'Propose FX hedges against currency exposure',
      'Monitor debt covenants and bank connectivity',
    ],
    agents: ['cash-positioning', 'liquidity-forecasting', 'fx-hedging', 'debt-covenants', 'bank-connectivity'],
  },
  {
    id: 'transactional', org: 'enterprise', navLabel: 'Transactional', title: 'Operational Finance', icon: '🧾', page: 'transactional',
    portals: ['anthropic', 'netsuite', 'sap'],
    blurb: 'AP, AR, payroll, procurement, billing, collections.',
    capabilities: [
      'Process AP invoices and schedule payment runs',
      'Run payroll and procurement workflows',
      'Issue billing and chase outstanding collections',
      'Apply incoming cash against receivables',
    ],
    agents: ['accounts-payable', 'payroll', 'procurement', 'billing', 'accounts-receivable', 'collections'],
  },
  {
    id: 'finops', org: 'enterprise', navLabel: 'FinOps', title: 'Finance Systems & Operations', icon: '⚙️', page: 'finops',
    portals: ['anthropic', 'snowflake', 'netsuite'],
    blurb: 'Data pipelines, dashboards, ERP admin, process transformation.',
    capabilities: [
      'Build and monitor finance data pipelines',
      'Publish self-serve dashboards and reporting',
      'Administer the ERP and its master data',
      'Drive order-to-cash / procure-to-pay process improvement',
    ],
    agents: ['data-pipelines', 'dashboards-reporting', 'erp-administration', 'process-transformation', 'o2c-p2p-process-owner'],
  },
  {
    id: 'corpdev', org: 'enterprise', navLabel: 'Corp Dev', title: 'Deal Room', icon: '🤝', page: 'corpdev',
    portals: ['anthropic', 'factset', 'sharepoint'],
    blurb: 'Pipeline, valuation, diligence, and deal materials.',
    capabilities: [
      'Source and screen the M&A deal pipeline',
      'Build valuation and accretion/dilution models',
      'Run due-diligence workstreams',
      'Produce CIMs and board-ready deal materials',
    ],
    agents: ['pipeline-sourcing', 'valuation-modelling', 'due-diligence', 'deal-materials', 'strategy-analysis', 'investor-relations'],
  },
  {
    id: 'audit', org: 'enterprise', navLabel: 'Internal Audit', title: 'Internal Audit & Controls', icon: '🔍', page: 'audit',
    portals: ['anthropic', 'sharepoint'],
    blurb: 'Audit planning, SOX controls, findings, and remediation.',
    capabilities: [
      'Plan the annual risk-based audit programme',
      'Test SOX controls and capture evidence',
      'Document findings and rate severity',
      'Track remediation actions through to closure',
    ],
    agents: ['audit-planning', 'sox-controls', 'findings-reporting', 'remediation-tracking'],
  },

  // ---------------- Financial Services ----------------
  {
    id: 'sales_trading_markets', org: 'financial-services', navLabel: 'Trading', title: 'Sales & Trading / Markets', icon: '📈', page: 'sales-trading',
    portals: ['anthropic', 'bloomberg', 'refinitiv'],
    blurb: 'Pricing, signals, structuring, pre-trade risk, execution.',
    capabilities: [
      'Price and quote client trades from live market data',
      'Generate quant signals and structure products',
      'Gate every order through pre-trade risk before it executes',
      'Execute and hedge — no trade fires without approval',
    ],
    agents: ['sales-coverage', 'pricing-quoting', 'quant-signals', 'structuring', 'pre-trade-risk-gate', 'execution-algo', 'risk-hedging'],
  },
  {
    id: 'investment_banking', org: 'financial-services', navLabel: 'Investment Banking', title: 'Investment Banking', icon: '💼', page: 'investment-banking',
    portals: ['anthropic', 'factset', 'sharepoint'],
    blurb: 'Coverage, modeling, materials, M&A and capital markets.',
    capabilities: [
      'Originate and cover clients with tailored ideas',
      'Build models and run buy/sell-side diligence',
      'Draft pitchbooks and deal materials',
      'Execute M&A and ECM/DCM deals behind a compliance gate',
    ],
    agents: ['coverage-origination', 'modeling-diligence', 'materials-drafting', 'compliance-gate', 'ma-execution', 'ecm-dcm-levfin', 'restructuring'],
  },
  {
    id: 'asset_investment_management', org: 'financial-services', navLabel: 'Asset Management', title: 'Asset & Investment Management', icon: '🗂️', page: 'asset-management',
    portals: ['anthropic', 'bloomberg', 'factset'],
    blurb: 'Macro, allocation, construction, mandate risk, execution.',
    capabilities: [
      'Form macro views and set asset allocation',
      'Construct portfolios to a target mandate',
      'Check mandate and risk limits before trading',
      'Execute buy-side orders within guardrails',
    ],
    agents: ['macro-strategy', 'asset-allocation', 'portfolio-construction', 'mandate-risk-gate', 'buyside-execution'],
  },
  {
    id: 'quantitative_data_technology', org: 'financial-services', navLabel: 'Quant', title: 'Quantitative, Data & Technology', icon: '🔬', page: 'quant',
    portals: ['anthropic', 'snowflake', 'refinitiv'],
    blurb: 'Pricing, research, risk models, and validation.',
    capabilities: [
      'Develop pricing and risk models',
      'Run quant research and systematic strategies',
      'Independently validate models before use',
      'Promote validated models into production',
    ],
    agents: ['quant-pricing', 'quant-research', 'risk-model-dev', 'data-science', 'financial-engineering', 'systematic-dev', 'model-validation', 'promote'],
  },
  {
    id: 'operations_middle_back_office', org: 'financial-services', navLabel: 'Operations', title: 'Operations — Middle & Back Office', icon: '🏗️', page: 'operations',
    portals: ['anthropic', 'swift', 'sap'],
    blurb: 'Trade support, settlements, custody, collateral.',
    capabilities: [
      'Support and confirm trades post-execution',
      'Settle, reconcile, and break-fix exceptions',
      'Run fund accounting and custody operations',
      'Manage collateral and margin calls',
    ],
    agents: ['trade-support', 'settlements', 'reconciliations', 'fund-accounting', 'custody-ops', 'collateral-mgmt'],
  },
  {
    id: 'retail_commercial_banking', org: 'financial-services', navLabel: 'Retail Banking', title: 'Retail & Commercial Banking', icon: '🏦', page: 'retail-commercial-banking',
    portals: ['anthropic', 'plaid', 'salesforce'],
    blurb: 'Personal & commercial banking, lending, branch ops.',
    capabilities: [
      'Serve personal and commercial banking clients',
      'Originate loans and analyse credit',
      'Underwrite applications against policy',
      'Fund approved loans — release gated by a human',
    ],
    agents: ['personal-banking', 'commercial-rm', 'branch-ops', 'loan-origination', 'credit-analysis', 'underwriting', 'loan-funding'],
  },
  {
    id: 'wealth_private_banking', org: 'financial-services', navLabel: 'Wealth', title: 'Wealth & Private Banking', icon: '💎', page: 'wealth-private-banking',
    portals: ['anthropic', 'salesforce', 'bloomberg'],
    blurb: 'Onboarding, planning, advice, suitability, discretionary PM.',
    capabilities: [
      'Onboard clients with KYC checks',
      'Build financial plans and personalised advice',
      'Verify suitability before any recommendation',
      'Run discretionary portfolios and private-banking credit',
    ],
    agents: ['client-onboarding-kyc', 'financial-planning', 'investment-advice', 'plan-reconciliation', 'suitability-gate', 'credit-gate', 'discretionary-pm', 'private-banking'],
  },
  {
    id: 'private_markets', org: 'financial-services', navLabel: 'Private Markets', title: 'Private Markets', icon: '🏗️', page: 'private-markets',
    portals: ['anthropic', 'factset', 'sharepoint'],
    blurb: 'Origination, PE/VC & credit underwriting, IC, stewardship.',
    capabilities: [
      'Build and triage the origination pipeline',
      'Underwrite PE/VC, credit, and real-asset deals',
      'Take deals through investment committee',
      'Steward portfolio companies post-commitment',
    ],
    agents: ['origination-pipeline', 'pe-vc-underwriting', 'credit-underwriting', 'real-asset-underwriting', 'fund-of-funds', 'ic-commitment', 'portfolio-stewardship'],
  },
  {
    id: 'product_strategy_client', org: 'financial-services', navLabel: 'Product', title: 'Product, Strategy & Client', icon: '🧭', page: 'product',
    portals: ['anthropic', 'salesforce'],
    blurb: 'Product, pricing, launch, distribution, client services.',
    capabilities: [
      'Manage product roadmap and pricing',
      'File for regulatory approval and launch',
      'Drive sales distribution to channels',
      'Onboard and service clients end to end',
    ],
    agents: ['product-management', 'pricing', 'compliance-filing', 'launch', 'sales-distribution', 'client-services', 'client-onboarding'],
  },
  {
    id: 'risk', org: 'financial-services', navLabel: 'Risk', title: 'Risk Management', icon: '🛡️',
    portals: ['anthropic', 'bloomberg', 'snowflake'],
    blurb: 'Market, credit, operational, liquidity & enterprise risk.',
    capabilities: [
      'Measure market, credit, liquidity and operational risk',
      'Independently validate risk models',
      'Aggregate exposures into an enterprise risk view',
      'Surface limit breaches for review',
    ],
    agents: ['market-risk', 'credit-risk', 'operational-risk', 'liquidity-risk', 'model-validation', 'erm-aggregation'],
  },
  {
    id: 'compliance', org: 'financial-services', navLabel: 'Compliance', title: 'Compliance & Financial Crime', icon: '⚖️',
    portals: ['anthropic', 'worldcheck', 'salesforce'],
    blurb: 'AML/KYC, sanctions, fraud, monitoring, regulatory affairs.',
    capabilities: [
      'Run AML/KYC onboarding and screening',
      'Screen counterparties against sanctions lists',
      'Investigate fraud and suspicious activity',
      'Monitor for breaches and manage regulatory affairs',
    ],
    agents: ['aml-kyc', 'sanctions-screening', 'fraud-investigation', 'compliance-monitoring', 'regulatory-affairs', 'legal-counsel'],
  },
  {
    id: 'insurance', org: 'financial-services', navLabel: 'Insurance', title: 'Insurance & Actuarial', icon: '🌂',
    portals: ['anthropic', 'snowflake'],
    blurb: 'Actuarial, cat modelling, underwriting, claims, reinsurance.',
    capabilities: [
      'Run actuarial reserving and catastrophe models',
      'Underwrite policies against risk appetite',
      'Adjudicate and process claims',
      'Manage reinsurance treaties and product design',
    ],
    agents: ['actuarial', 'cat-modelling', 'underwriting', 'claims', 'reinsurance', 'product'],
  },
]

export const GROUPS_BY_ID: Record<string, AgentGroup> = Object.fromEntries(GROUPS.map((g) => [g.id, g]))

export function groupsForOrg(orgId: string): AgentGroup[] {
  return GROUPS.filter((g) => g.org === orgId)
}

// ---- display helpers --------------------------------------------------------

// Words that should render fully upper-cased / specially in agent names.
const ACRONYMS: Record<string, string> = {
  fx: 'FX', ma: 'M&A', ecm: 'ECM', dcm: 'DCM', levfin: 'LevFin', pe: 'PE', vc: 'VC',
  aml: 'AML', kyc: 'KYC', erp: 'ERP', sox: 'SOX', erm: 'ERM', rm: 'RM', ic: 'IC',
  pm: 'PM', o2c: 'O2C', p2p: 'P2P', etr: 'ETR', mgmt: 'Mgmt',
}

/** Turn a kebab-case subagent slug (`pre-trade-risk-gate`) into a readable
 *  label (`Pre Trade Risk Gate`) for display. */
export function humanizeAgent(slug: string): string {
  return slug
    .split('-')
    .map((w) => ACRONYMS[w] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** A "gate" subagent is a hard human-approval checkpoint in the flow. */
export function isGateAgent(slug: string): boolean {
  return /gate|signoff|sign-off|compliance|risk-gate/.test(slug)
}
