// Operations (Middle & Back Office) dashboard.
//
// A trade lifecycle board driven by the SSE JobTimeline (confirm -> settle ->
// reconcile turns green as workers finish) and the human-in-the-loop
// ApprovalDrawer for settlement instructions, which are default-deny: a trade is
// never settled until a controller approves (and an unconfirmed trade is refused
// outright, so no approval is ever raised for it).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startProcess } from './api'

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface OperationsPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function OperationsPage({ eventSource }: OperationsPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [tradeId, setTradeId] = useState('T1')
  const [amount, setAmount] = useState('1000')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('ops_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runProcess = useCallback(async () => {
    setEvents([])
    const { job_id } = await startProcess({ trade_id: tradeId, amount: Number(amount) || 0 })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource, tradeId, amount])

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
    <div className="operations-page">
      <header>
        <h1>Operations — Middle &amp; Back Office</h1>
      </header>

      <section aria-label="Trade lifecycle">
        <h2>Trade lifecycle</h2>
        <p className="section-desc">
          Push a trade through the post-execution pipeline — confirm → settle → reconcile. Enter the
          trade reference and notional, then run it: each stage turns green as a subagent finishes,
          and the settlement step pauses for your approval below.
        </p>
        <div className="field-row">
          <label>
            Trade id
            <input value={tradeId} onChange={(e) => setTradeId(e.target.value)} placeholder="T1" />
            <span className="field-hint">Reference of the executed trade to process.</span>
          </label>
          <label>
            Notional amount
            <input
              type="number"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="1000"
            />
            <span className="field-hint">Trade value to settle, in base currency.</span>
          </label>
        </div>
        <button type="button" onClick={() => void runProcess()}>
          Process trade
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Settlement approvals">
        <h2>Settlement instructions</h2>
        <p className="section-desc">
          Settlements are default-deny: a confirmed trade waits here until a controller approves the
          instruction. Click an item to review the rationale, then approve to release cash or reject
          to hold it. Nothing settles without a human.
        </p>
        {approvals.length === 0 ? (
          <p>No settlement instructions awaiting approval</p>
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
