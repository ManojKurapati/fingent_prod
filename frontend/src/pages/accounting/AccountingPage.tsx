// Accounting & Controllership close cockpit.
//
// A live close checklist driven by the SSE JobTimeline (sub-ledger rows turn green
// as workers finish), plus the human-in-the-loop ApprovalDrawer for the GL
// journal-entry post — nothing posts to the ledger without explicit approval.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startClose } from './api'

const PERIOD = 'FY26-M06'
const ENTITIES = ['e1', 'e2', 'e3']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface AccountingPageProps {
  // Injectable EventSource so the live checklist is testable without a browser.
  eventSource?: EventSourceImpl
}

export function AccountingPage({ eventSource }: AccountingPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('accounting_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runClose = useCallback(async () => {
    setEvents([])
    const { job_id } = await startClose({ period: PERIOD, entities: ENTITIES })
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
    <div className="accounting-page">
      <header>
        <h1>Accounting Close</h1>
      </header>

      <section aria-label="Close checklist">
        <h2>Period close</h2>
        <button type="button" onClick={() => void runClose()}>
          Start close
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Ledger post approvals">
        <h2>Journal-entry approvals</h2>
        {approvals.length === 0 ? (
          <p>No ledger posts awaiting approval</p>
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
