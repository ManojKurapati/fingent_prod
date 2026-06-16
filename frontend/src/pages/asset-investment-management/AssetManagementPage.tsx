// Asset & Investment Management dashboard.
//
// Runs a rebalance (macro->allocation spine ‖ research fan-out -> construction ->
// mandate/risk gate -> gated execution) and streams subagent progress into the
// live JobTimeline. A standalone research fan-out can be kicked off independently.
// Order placement is consequential: it surfaces in the ApprovalDrawer as a PM
// sign-off and is withheld entirely when the mandate/risk gate denies.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startRebalance, startResearch } from './api'

const PORTFOLIO_ID = 'pf1'
const NAMES = ['n1', 'n2', 'n3']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface AssetManagementPageProps {
  eventSource?: EventSourceImpl
}

export function AssetManagementPage({ eventSource }: AssetManagementPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [researchJob, setResearchJob] = useState<string | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('aim_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runRebalance = useCallback(async () => {
    setEvents([])
    const { job_id } = await startRebalance({ portfolio_id: PORTFOLIO_ID, names: NAMES })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const runResearch = useCallback(async () => {
    const { job_id } = await startResearch({ names: NAMES })
    setResearchJob(job_id)
  }, [])

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
    <div className="asset-management-page">
      <header>
        <h1>Asset &amp; Investment Management</h1>
      </header>

      <section aria-label="Rebalance">
        <h2>Proposed rebalance</h2>
        <button type="button" onClick={() => void runRebalance()}>
          Run rebalance
        </button>
        <button type="button" onClick={() => void runResearch()}>
          Run research
        </button>
        {researchJob && <p>Research job: {researchJob}</p>}
        <JobTimeline events={events} />
      </section>

      <section aria-label="Trade approvals">
        <h2>Trade-list approvals</h2>
        {approvals.length === 0 ? (
          <p>No trade approvals pending</p>
        ) : (
          <ul>
            {approvals.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => setSelected(a)}>
                  {a.tool_name} — {a.rationale}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ApprovalDrawer
        approval={selected}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}
