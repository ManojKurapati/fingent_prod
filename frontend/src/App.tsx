// Application shell — header, nav, and the shared approvals region. Per-group
// dashboards mount under the main content area; the home view keeps the global
// human-in-the-loop approvals queue.

import { useCallback, useEffect, useState } from 'react'
import { ApprovalDrawer } from './components/ApprovalDrawer'
import { approveRequest, listApprovals, rejectRequest } from './lib/api'
import type { Approval } from './lib/types'
import { FpaPage } from './pages/fpa/FpaPage'
import { SalesTradingPage } from './pages/sales-trading-markets/SalesTradingPage'

type View = 'home' | 'fpa' | 'trading'

export function App() {
  const [view, setView] = useState<View>('home')
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)

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

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>AI-Native Finance Platform</h1>
        <nav aria-label="Agent groups">
          <button type="button" onClick={() => setView('home')}>
            Home
          </button>
          <button type="button" onClick={() => setView('fpa')}>
            FP&amp;A
          </button>
          <button type="button" onClick={() => setView('trading')}>
            Trading
          </button>
        </nav>
      </header>

      {view === 'fpa' && <FpaPage />}
      {view === 'trading' && <SalesTradingPage />}

      {view === 'home' && (
        <main>
          <section aria-label="Approvals queue">
            <h2>Approvals</h2>
            {approvals.length === 0 ? (
              <p>No pending approvals</p>
            ) : (
              <ul>
                {approvals.map((a) => (
                  <li key={a.id}>
                    <button type="button" onClick={() => setSelected(a)}>
                      {a.tool_name} — {a.approver_role}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </main>
      )}

      <ApprovalDrawer
        approval={selected}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}
