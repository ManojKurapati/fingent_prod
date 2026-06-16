// Investment Banking deal workspace.
//
// Runs a mandate (origination -> diligence -> {materials ‖ compliance-gate} ->
// gated execution) and streams subagent progress into the live JobTimeline. The
// client-facing launch is consequential: it surfaces in the ApprovalDrawer as a
// wall-crossing / conflicts sign-off and is withheld entirely when the compliance
// gate denies, so there is nothing to approve on a conflicted deal.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { type DealType, startMandate } from './api'

const DEAL_ID = 'd1'
const CLIENT = 'acme'
const DEAL_TYPES: DealType[] = ['ma', 'ecm', 'dcm', 'levfin', 'restructuring']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface InvestmentBankingPageProps {
  // Injectable EventSource so the live timeline is testable without a browser.
  eventSource?: EventSourceImpl
}

export function InvestmentBankingPage({ eventSource }: InvestmentBankingPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [dealType, setDealType] = useState<DealType>('ma')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('ib_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runMandate = useCallback(async () => {
    setEvents([])
    const { job_id } = await startMandate({
      deal_id: DEAL_ID,
      client: CLIENT,
      deal_type: dealType,
      sector: 'tech',
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [dealType, eventSource])

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
    <div className="investment-banking-page">
      <header>
        <h1>Investment Banking</h1>
      </header>

      <section aria-label="Deal mandate">
        <h2>Deal mandate</h2>
        <label>
          Deal type
          <select value={dealType} onChange={(e) => setDealType(e.target.value as DealType)}>
            {DEAL_TYPES.map((dt) => (
              <option key={dt} value={dt}>
                {dt}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void runMandate()}>
          Run mandate
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Wall-crossing approvals">
        <h2>Wall-crossing / launch approvals</h2>
        {approvals.length === 0 ? (
          <p>No launch approvals pending</p>
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
