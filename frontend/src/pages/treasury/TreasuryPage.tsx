// Treasury dashboard.
//
// Runs the daily-position sequence (live JobTimeline as the cash → liquidity →
// hedging/covenants spine streams), and exposes the gated cash-movement actions
// (hedge execution and sweep). Each execution is default-deny: it surfaces in the
// ApprovalDrawer and fires only after a Treasurer approves it.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { executeHedge, executeSweep, startDailyPosition } from './api'

const AS_OF = '2026-06-16'
const ACCOUNTS = ['a1', 'a2']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface TreasuryPageProps {
  // Injectable EventSource so the live spine is testable without a browser.
  eventSource?: EventSourceImpl
}

export function TreasuryPage({ eventSource }: TreasuryPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('treasury_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runDailyPosition = useCallback(async () => {
    setEvents([])
    const { job_id } = await startDailyPosition({ as_of: AS_OF, accounts: ACCOUNTS })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const requestHedge = useCallback(async () => {
    await executeHedge({ pair: 'EURUSD', notional: 500 })
    void refresh()
  }, [refresh])

  const requestSweep = useCallback(async () => {
    await executeSweep({ from_account: 'a1', to_account: 'a2', amount: 250 })
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
    <div className="treasury-page">
      <header>
        <h1>Treasury</h1>
      </header>

      <section aria-label="Daily position">
        <h2>Daily cash position</h2>
        <button type="button" onClick={() => void runDailyPosition()}>
          Run daily position
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Cash movement">
        <h2>Cash movement (gated)</h2>
        <button type="button" onClick={() => void requestHedge()}>
          Execute hedge
        </button>
        <button type="button" onClick={() => void requestSweep()}>
          Sweep cash
        </button>
      </section>

      <section aria-label="Cash movement approvals">
        <h2>Pending cash-movement approvals</h2>
        {approvals.length === 0 ? (
          <p>No cash movements awaiting approval</p>
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
