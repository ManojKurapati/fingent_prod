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
  const [hedgePair, setHedgePair] = useState('EURUSD')
  const [hedgeNotional, setHedgeNotional] = useState('500')
  const [sweepFrom, setSweepFrom] = useState('a1')
  const [sweepTo, setSweepTo] = useState('a2')
  const [sweepAmount, setSweepAmount] = useState('250')
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
    await executeHedge({ pair: hedgePair, notional: Number(hedgeNotional) || 0 })
    void refresh()
  }, [refresh, hedgePair, hedgeNotional])

  const requestSweep = useCallback(async () => {
    await executeSweep({
      from_account: sweepFrom,
      to_account: sweepTo,
      amount: Number(sweepAmount) || 0,
    })
    void refresh()
  }, [refresh, sweepFrom, sweepTo, sweepAmount])

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
        <p className="section-desc">
          Builds today's consolidated cash picture across bank accounts. Press Run daily position and
          the cash → liquidity → hedging/covenants spine streams live, turning green as each subagent
          finishes. This step is read-only — it reports positions and does not move any cash.
        </p>
        <button type="button" onClick={() => void runDailyPosition()}>
          Run daily position
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Cash movement">
        <h2>Cash movement (gated)</h2>
        <p className="section-desc">
          Initiates real cash moves — an FX hedge or an inter-account sweep. Set the trade details
          below and press the action; because these are default-deny, nothing executes immediately.
          Each request surfaces in the pending approvals list below and only fires once a Treasurer
          signs off.
        </p>
        <div className="field-row">
          <label>
            Hedge pair
            <input
              value={hedgePair}
              onChange={(e) => setHedgePair(e.target.value)}
              placeholder="EURUSD"
            />
            <span className="field-hint">FX pair to hedge, e.g. EURUSD.</span>
          </label>
          <label>
            Hedge notional
            <input
              type="number"
              min="0"
              value={hedgeNotional}
              onChange={(e) => setHedgeNotional(e.target.value)}
              placeholder="500"
            />
            <span className="field-hint">Notional to hedge, in base currency.</span>
          </label>
        </div>
        <button type="button" onClick={() => void requestHedge()}>
          Execute hedge
        </button>
        <div className="field-row">
          <label>
            Sweep from
            <input
              value={sweepFrom}
              onChange={(e) => setSweepFrom(e.target.value)}
              placeholder="a1"
            />
            <span className="field-hint">Source account to debit.</span>
          </label>
          <label>
            Sweep to
            <input value={sweepTo} onChange={(e) => setSweepTo(e.target.value)} placeholder="a2" />
            <span className="field-hint">Destination account to credit.</span>
          </label>
          <label>
            Sweep amount
            <input
              type="number"
              min="0"
              value={sweepAmount}
              onChange={(e) => setSweepAmount(e.target.value)}
              placeholder="250"
            />
            <span className="field-hint">Cash to move between the accounts.</span>
          </label>
        </div>
        <button type="button" onClick={() => void requestSweep()}>
          Sweep cash
        </button>
      </section>

      <section aria-label="Cash movement approvals">
        <h2>Pending cash-movement approvals</h2>
        <p className="section-desc">
          A human-in-the-loop gate for cash moves: held hedges and sweeps wait here until a Treasurer
          signs off. Click an item to review the instruction and rationale, then approve to release
          the cash or reject to hold it — nothing moves without approval.
        </p>
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
