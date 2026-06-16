// Retail & Commercial Banking dashboard — the lending pipeline kanban. A live
// JobTimeline greens each stage (origination → analysis → underwriting → funding)
// as workers finish, and the underwriter decision panel — the credit-policy gate —
// approves the consequential disbursement through the shared ApprovalDrawer
// (default-deny, human-in-the-loop).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startApplication } from './api'

const APPLICATION_ID = 'a1'
const CHANNEL = 'personal' as const

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface RetailCommercialBankingPageProps {
  // Injectable EventSource so the live kanban is testable without a browser.
  eventSource?: EventSourceImpl
}

export function RetailCommercialBankingPage({ eventSource }: RetailCommercialBankingPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('banking_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runApplication = useCallback(async () => {
    setEvents([])
    const { job_id } = await startApplication({
      application_id: APPLICATION_ID,
      channel: CHANNEL,
      applicant: 'ann',
      loan_amount: 100,
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

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
    <div className="retail-commercial-banking-page">
      <header>
        <h1>Retail &amp; Commercial Banking</h1>
      </header>

      <section aria-label="Lending pipeline">
        <h2>Lending pipeline</h2>
        <button type="button" onClick={() => void runApplication()}>
          Start application
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Underwriter decisions">
        <h2>Underwriter decisions</h2>
        {approvals.length === 0 ? (
          <p>No disbursements pending</p>
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
