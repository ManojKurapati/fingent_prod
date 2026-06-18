// Transactional / Operational Finance dashboard.
//
// Operational queues per lane: a live cycle timeline (lane rows turn green as
// workers finish), an AP payment-run trigger, and the human-in-the-loop
// ApprovalDrawer that gates every cash movement (AP runs, payroll disbursement).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startCycle, startPaymentRun } from './api'

const PERIOD = '2026-06'
const VENDORS = ['v1', 'v2']
const CUSTOMERS = ['c1', 'c2']
const EMPLOYEES = ['e1']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface TransactionalPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function TransactionalPage({ eventSource }: TransactionalPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('transactional_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const subscribe = useCallback(
    (job_id: string) => {
      setEvents([])
      unsubscribe.current?.()
      unsubscribe.current = subscribeJob(
        job_id,
        { onEvent: (event) => setEvents((prev) => [...prev, event]) },
        eventSource,
      )
    },
    [eventSource],
  )

  const runCycle = useCallback(async () => {
    const { job_id } = await startCycle({
      period: PERIOD,
      vendors: VENDORS,
      customers: CUSTOMERS,
      employees: EMPLOYEES,
    })
    subscribe(job_id)
  }, [subscribe])

  const runPaymentRun = useCallback(async () => {
    const { job_id } = await startPaymentRun({ period: PERIOD, vendors: VENDORS })
    subscribe(job_id)
    void refresh()
  }, [subscribe, refresh])

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
    <div className="transactional-page">
      <header>
        <h1>Operational Finance</h1>
      </header>

      <section aria-label="Operational cycle">
        <h2>Operational cycle</h2>
        <p className="section-desc">
          Drives the operational-finance lanes for the period — billing/AR, AP, and payroll. Run
          cycle streams every lane live (each row greens as its subagent finishes); Run AP payment
          run triggers the accounts-payable disbursement, which is a cash move and surfaces for
          approval below before any funds leave.
        </p>
        <button type="button" onClick={() => void runCycle()}>
          Run cycle
        </button>
        <button type="button" onClick={() => void runPaymentRun()}>
          Run AP payment run
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Payment approvals">
        <h2>Cash-movement approvals</h2>
        <p className="section-desc">
          A human-in-the-loop gate for outbound cash: AP runs and payroll disbursements wait here
          until approved. Click an item to review the beneficiaries, amount and rationale, then
          approve to release payment or reject to hold — no cash leaves without your sign-off.
        </p>
        {approvals.length === 0 ? (
          <p>No payment approvals</p>
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
