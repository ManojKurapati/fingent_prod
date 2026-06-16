// Private Markets dashboard — deal underwriting workspace + Investment Committee
// review-and-vote. A live diligence/underwriting grid (SSE JobTimeline) greens as
// workers finish; the IC memo capital commitment is approved through the shared
// ApprovalDrawer (default-deny, human-in-the-loop), and a portfolio monitor surfaces
// covenant/KPI alerts.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, getJob, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startDeal, startMonitor } from './api'

const DEAL_ID = 'd1'
const ASSET_CLASS = 'credit' as const
const PORTFOLIO_ID = 'p1'

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface PrivateMarketsPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function PrivateMarketsPage({ eventSource }: PrivateMarketsPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [alerts, setAlerts] = useState<string[] | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('pm_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runDeal = useCallback(async () => {
    setEvents([])
    const { job_id } = await startDeal({
      deal_id: DEAL_ID,
      asset_class: ASSET_CLASS,
      sponsor: 'acme',
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const runMonitor = useCallback(async () => {
    const { job_id } = await startMonitor({ portfolio_id: PORTFOLIO_ID })
    const job = await getJob(job_id)
    const stewardship = (job.result as Record<string, { alerts?: string[] }> | null)?.[
      'portfolio-stewardship'
    ]
    setAlerts(stewardship?.alerts ?? [])
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
    <div className="private-markets-page">
      <header>
        <h1>Private Markets</h1>
      </header>

      <section aria-label="Deal underwriting">
        <h2>Deal underwriting</h2>
        <button type="button" onClick={() => void runDeal()}>
          Underwrite deal
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Portfolio monitor">
        <h2>Portfolio monitor</h2>
        <button type="button" onClick={() => void runMonitor()}>
          Run monitor
        </button>
        {alerts && (
          <p>{alerts.length === 0 ? 'No covenant alerts' : `Alerts: ${alerts.join(', ')}`}</p>
        )}
      </section>

      <section aria-label="IC memo review">
        <h2>Investment Committee — capital commitments</h2>
        {approvals.length === 0 ? (
          <p>No capital commitments pending</p>
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
