// Application shell — header, nav, and the shared approvals region. Per-group
// dashboards (wave 2/3) mount under the main content area.

import { useCallback, useEffect, useState } from 'react'
import { ApprovalDrawer } from './components/ApprovalDrawer'
import { approveRequest, listApprovals, rejectRequest } from './lib/api'
import type { Approval } from './lib/types'

export function App() {
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
          <span>Dashboards mount here</span>
        </nav>
      </header>

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

      <ApprovalDrawer
        approval={selected}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}
