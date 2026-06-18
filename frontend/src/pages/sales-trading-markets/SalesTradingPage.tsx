// Sales & Trading / Markets desk blotter.
//
// Submits an order (parallel feeds -> pre-trade risk gate -> gated execution) and
// streams subagent progress into the live JobTimeline. Order routing is
// consequential: it surfaces in the ApprovalDrawer as a limit/trader sign-off and
// is withheld entirely when the pre-trade risk gate denies (over-limit / unsuitable),
// so there is nothing to approve on a blocked order.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { type Side, startOrder } from './api'

const ORDER_ID = 'o1'
const ACCOUNT = 'acct1'
const INSTRUMENT = 'AAPL'
const BOOK = 'eqbook'
const QUANTITY = 5

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface SalesTradingPageProps {
  eventSource?: EventSourceImpl
}

export function SalesTradingPage({ eventSource }: SalesTradingPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [side, setSide] = useState<Side>('buy')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('markets_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runOrder = useCallback(async () => {
    setEvents([])
    const { job_id } = await startOrder({
      order_id: ORDER_ID,
      account: ACCOUNT,
      instrument: INSTRUMENT,
      side,
      quantity: QUANTITY,
      book: BOOK,
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      {
        onEvent: (event) => {
          setEvents((prev) => [...prev, event])
          // When the run finishes, any routing request is now in the queue.
          if (event.type === 'status') void refresh()
        },
      },
      eventSource,
    )
  }, [side, eventSource, refresh])

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
    <div className="sales-trading-page">
      <header>
        <h1>Sales &amp; Trading / Markets</h1>
      </header>

      <section aria-label="Desk blotter">
        <h2>Desk blotter</h2>
        <p className="section-desc">
          Stage a markets order and run it through the desk pipeline — parallel feeds → pre-trade
          risk gate → gated execution. Pick the side, then submit: the timeline greens as each
          subagent finishes, and if the order clears the risk gate it surfaces below as a
          trader/limit sign-off. Nothing routes to market until that approval is granted, and an
          over-limit or unsuitable order is blocked outright with nothing to approve.
        </p>
        <label>
          Side
          <select value={side} onChange={(e) => setSide(e.target.value as Side)}>
            <option value="buy">buy</option>
            <option value="sell">sell</option>
          </select>
          <span className="field-hint">Buy or sell direction for the order.</span>
        </label>
        <button type="button" onClick={() => void runOrder()}>
          Submit order
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Routing approvals">
        <h2>Order routing approvals</h2>
        <p className="section-desc">
          These are the human-in-the-loop gates for order routing. Each item is an order that
          cleared the pre-trade risk gate and is now waiting on a trader/limit sign-off. Click one to
          review the rationale, then approve to release it to market or reject to hold it — no order
          is routed without an approval here.
        </p>
        {approvals.length === 0 ? (
          <p>No routing approvals pending</p>
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
