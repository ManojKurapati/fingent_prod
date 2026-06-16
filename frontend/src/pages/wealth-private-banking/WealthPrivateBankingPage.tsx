// Wealth & Private Banking dashboard — client 360 with a live onboarding/planning
// grid (SSE JobTimeline), and the suitability sign-off panel advisors must clear
// before any discretionary rebalance or Lombard facility books. The consequential
// asset move / credit extension is approved through the shared ApprovalDrawer
// (default-deny, human-in-the-loop).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startCredit, startOnboarding, startRebalance } from './api'

const CLIENT_ID = 'c1'

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface WealthPrivateBankingPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function WealthPrivateBankingPage({ eventSource }: WealthPrivateBankingPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('wealth_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runOnboarding = useCallback(async () => {
    setEvents([])
    const { job_id } = await startOnboarding({ client_id: CLIENT_ID, segment: 'hnw', name: 'Ada' })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const proposeRebalance = useCallback(async () => {
    await startRebalance({ client_id: CLIENT_ID, proposed_risk: 0.5 })
    void refresh()
  }, [refresh])

  const proposeCredit = useCallback(async () => {
    await startCredit({ client_id: CLIENT_ID, loan_amount: 400, facility: 'lombard' })
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
    <div className="wealth-private-banking-page">
      <header>
        <h1>Wealth &amp; Private Banking</h1>
      </header>

      <section aria-label="Client onboarding">
        <h2>Client onboarding &amp; plan</h2>
        <button type="button" onClick={() => void runOnboarding()}>
          Onboard client
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Suitability actions">
        <h2>Proposed actions</h2>
        <button type="button" onClick={() => void proposeRebalance()}>
          Propose rebalance
        </button>
        <button type="button" onClick={() => void proposeCredit()}>
          Propose Lombard facility
        </button>
      </section>

      <section aria-label="Suitability sign-off">
        <h2>Suitability sign-off</h2>
        {approvals.length === 0 ? (
          <p>No actions pending sign-off</p>
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
