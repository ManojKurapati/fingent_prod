// Application shell — glass sidebar, top bar, and the command-center home with
// the global human-in-the-loop approvals queue. The sidebar wires every group
// dashboard; the Agent Catalog and Integrations views handle deployment and
// portal connections.

import { useCallback, useEffect, useState, type ComponentType } from 'react'
import { AgentCatalog } from './components/AgentCatalog'
import { ApprovalDrawer } from './components/ApprovalDrawer'
import { Integrations } from './components/Integrations'
import { approveRequest, listApprovals, rejectRequest } from './lib/api'
import { GROUPS, ORGANISATIONS, groupsForOrg } from './lib/catalog'
import { usePlatformStore } from './lib/deployments'
import type { Approval } from './lib/types'

import { AccountingPage } from './pages/accounting/AccountingPage'
import { AssetManagementPage } from './pages/asset-investment-management/AssetManagementPage'
import { AuditPage } from './pages/audit/AuditPage'
import { CorpDevPage } from './pages/corpdev/CorpDevPage'
import { FinOpsPage } from './pages/finops/FinOpsPage'
import { FpaPage } from './pages/fpa/FpaPage'
import { InvestmentBankingPage } from './pages/investment-banking/InvestmentBankingPage'
import { LeadershipPage } from './pages/leadership/LeadershipPage'
import { OperationsPage } from './pages/operations-middle-back-office/OperationsPage'
import { PrivateMarketsPage } from './pages/private-markets/PrivateMarketsPage'
import { ProductPage } from './pages/product-strategy-client/ProductPage'
import { QuantPage } from './pages/quantitative-data-technology/QuantPage'
import { RetailCommercialBankingPage } from './pages/retail-commercial-banking/RetailCommercialBankingPage'
import { SalesTradingPage } from './pages/sales-trading-markets/SalesTradingPage'
import { TaxPage } from './pages/tax/TaxPage'
import { TransactionalPage } from './pages/transactional/TransactionalPage'
import { TreasuryPage } from './pages/treasury/TreasuryPage'
import { WealthPrivateBankingPage } from './pages/wealth-private-banking/WealthPrivateBankingPage'

// Group dashboard view-id -> component. Keys match AgentGroup.page in catalog.ts.
const PAGES: Record<string, ComponentType> = {
  leadership: LeadershipPage,
  fpa: FpaPage,
  accounting: AccountingPage,
  tax: TaxPage,
  treasury: TreasuryPage,
  transactional: TransactionalPage,
  finops: FinOpsPage,
  corpdev: CorpDevPage,
  audit: AuditPage,
  'sales-trading': SalesTradingPage,
  'investment-banking': InvestmentBankingPage,
  'asset-management': AssetManagementPage,
  quant: QuantPage,
  operations: OperationsPage,
  'retail-commercial-banking': RetailCommercialBankingPage,
  'wealth-private-banking': WealthPrivateBankingPage,
  'private-markets': PrivateMarketsPage,
  product: ProductPage,
}

const TITLES: Record<string, string> = {
  home: 'Command Center',
  catalog: 'Agent Catalog',
  integrations: 'Integrations',
  ...Object.fromEntries(GROUPS.filter((g) => g.page).map((g) => [g.page as string, g.title])),
}

export function App() {
  const [view, setView] = useState<string>('home')
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const { deployments, connections } = usePlatformStore()

  const refresh = useCallback(async () => {
    try {
      setApprovals(await listApprovals())
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleApprove = useCallback(
    async (approver: string) => {
      if (selected) await approveRequest(selected.id, approver)
      setSelected(null)
      void refresh()
    },
    [selected, refresh],
  )

  const handleReject = useCallback(
    async (approver: string, reason: string) => {
      if (selected) await rejectRequest(selected.id, approver, reason)
      setSelected(null)
      void refresh()
    },
    [selected, refresh],
  )

  const PageComponent = PAGES[view]
  const deployedCount = Object.keys(deployments).length
  const connectedCount = Object.keys(connections).length

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◆
          </span>
          <span className="brand-text">
            <h1>Fingent</h1>
            <span>Your AI Native Financial Services Platform</span>
          </span>
        </div>

        <nav className="nav-group" aria-label="Platform">
          <span className="nav-group-label">Platform</span>
          <NavButton id="home" label="Home" icon="🏠" view={view} onSelect={setView} />
          <NavButton id="catalog" label="Agent Catalog" icon="🧩" view={view} onSelect={setView} />
          <NavButton id="integrations" label="Integrations" icon="🔌" view={view} onSelect={setView} />
        </nav>

        {ORGANISATIONS.map((org) => (
          <nav className="nav-group" aria-label={org.name} key={org.id}>
            <span className="nav-group-label">{org.name}</span>
            {groupsForOrg(org.id)
              .filter((g) => g.page)
              .map((g) => (
                <NavButton
                  key={g.id}
                  id={g.page as string}
                  label={g.navLabel}
                  icon={g.icon}
                  view={view}
                  onSelect={setView}
                />
              ))}
          </nav>
        ))}

        <div className="sidebar-foot">
          <span className="pill">
            <span className="dot" /> {deployedCount} agents live
          </span>
        </div>
      </aside>

      <main className="app-main">
        <div className="topbar">
          <span className="topbar-title">{TITLES[view] ?? 'Dashboard'}</span>
          <div className="topbar-right">
            <span className="pill">
              🔌 {connectedCount} portals
            </span>
            <button type="button" className="pill pill-btn" onClick={() => setView('home')}>
              Approvals
              <span className="badge-count" data-zero={approvals.length === 0}>
                {approvals.length}
              </span>
            </button>
            <span className="user-chip">
              <span className="avatar">FN</span>
              Finance Ops
            </span>
          </div>
        </div>

        {view === 'home' && (
          <HomeView
            approvals={approvals}
            onSelect={setSelected}
            deployedCount={deployedCount}
            connectedCount={connectedCount}
            onNavigate={setView}
          />
        )}

        {view === 'catalog' && <AgentCatalog onOpen={(p) => setView(p)} />}
        {view === 'integrations' && <Integrations />}
        {PageComponent && <PageComponent />}
      </main>

      <ApprovalDrawer
        approval={selected}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}

interface NavButtonProps {
  id: string
  label: string
  icon: string
  view: string
  onSelect: (id: string) => void
}

function NavButton({ id, label, icon, view, onSelect }: NavButtonProps) {
  return (
    <button
      type="button"
      className="nav-btn"
      aria-current={view === id}
      onClick={() => onSelect(id)}
    >
      <span className="nav-ico" aria-hidden="true">
        {icon}
      </span>
      {label}
    </button>
  )
}

interface HomeViewProps {
  approvals: Approval[]
  onSelect: (a: Approval) => void
  deployedCount: number
  connectedCount: number
  onNavigate: (view: string) => void
}

function HomeView({ approvals, onSelect, deployedCount, connectedCount, onNavigate }: HomeViewProps) {
  return (
    <>
      <div className="hero">
        <h2>Your AI finance organisation</h2>
        <p>
          Every functional group is an orchestrator agent; every responsibility is a subagent.
          Deploy groups from the catalog, connect your portals, and approve consequential actions
          here — nothing posts, pays, trades, or files without a human.
        </p>
      </div>

      <div className="stat-grid">
        <StatCard k="Agents deployed" v={String(deployedCount)} accent />
        <StatCard k="Portals connected" v={String(connectedCount)} />
        <StatCard k="Pending approvals" v={String(approvals.length)} />
        <StatCard k="Agent groups" v={String(GROUPS.length)} />
      </div>

      <main>
        <section aria-label="Approvals queue">
          <h2>Approvals</h2>
          {approvals.length === 0 ? (
            <p>No pending approvals</p>
          ) : (
            <ul>
              {approvals.map((a) => (
                <li key={a.id}>
                  <button type="button" onClick={() => onSelect(a)}>
                    {a.tool_name} — {a.approver_role}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Quick actions">
          <h2>Get started</h2>
          <div className="cta-row">
            <button type="button" className="btn" onClick={() => onNavigate('catalog')}>
              🧩 Browse Agent Catalog
            </button>
            <button type="button" className="btn ghost" onClick={() => onNavigate('integrations')}>
              🔌 Connect Integrations
            </button>
          </div>
        </section>
      </main>
    </>
  )
}

function StatCard({ k, v, accent }: { k: string; v: string; accent?: boolean }) {
  return (
    <div className="stat-card">
      <div className="k">{k}</div>
      <div className={`v ${accent ? 'accent' : ''}`}>{v}</div>
    </div>
  )
}
