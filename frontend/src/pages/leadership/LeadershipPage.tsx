// Leadership (CFO) executive cockpit.
//
// Pulls together the shared platform primitives: a live board-pack synthesis grid
// driven by the SSE JobTimeline (steps turn green as workers finish), a capital
// scenario sandbox, and the human-in-the-loop ApprovalDrawer for the CFO gate on
// publishing the board pack.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, getJob, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startBoardPack, startCapitalScenario } from './api'

const PERIOD = 'FY26'
const DIVISIONS = ['emea', 'amer', 'apac']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface LeadershipPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

interface CapitalResult {
  leverage: number
  recommendation: string
}

export function LeadershipPage({ eventSource }: LeadershipPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [target, setTarget] = useState('0.4')
  const [capital, setCapital] = useState<CapitalResult | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('leadership_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runBoardPack = useCallback(async () => {
    setEvents([])
    const { job_id } = await startBoardPack({
      period: PERIOD,
      divisions: DIVISIONS,
      target_leverage: Number(target) || 0.4,
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource, target])

  const runCapital = useCallback(async () => {
    const { job_id } = await startCapitalScenario({
      period: PERIOD,
      divisions: DIVISIONS,
      target_leverage: Number(target) || 0.4,
    })
    const job = await getJob(job_id)
    const result = (job.result as Record<string, CapitalResult> | null)?.['capital-strategy']
    if (result) setCapital({ leverage: result.leverage, recommendation: result.recommendation })
  }, [target])

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
    <div className="leadership-page">
      <header>
        <h1>Executive Cockpit</h1>
      </header>

      <section aria-label="Board pack synthesis">
        <h2>Board pack synthesis</h2>
        <p className="section-desc">
          Assembles the quarterly CFO board pack — division roll-ups and capital strategy — running it
          against the target leverage you set in the sandbox below; each step turns green as a worker
          finishes. When complete, publishing the pack waits on the CFO approval gate further down.
        </p>
        <button type="button" onClick={() => void runBoardPack()}>
          Run board pack
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Capital scenario sandbox">
        <h2>Capital scenario sandbox</h2>
        <p className="section-desc">
          A read-only what-if on the balance sheet: set a target leverage ratio and run it to see the
          modelled leverage and a financing recommendation. Nothing is committed — use it to size the
          capital structure before the board pack run picks up the same target.
        </p>
        <label>
          Target leverage
          <input
            type="number"
            step="0.05"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="0.4"
          />
          <span className="field-hint">
            Target net-debt-to-EBITDA ratio, e.g. 0.4 for 40%.
          </span>
        </label>
        <button type="button" onClick={() => void runCapital()}>
          Run capital scenario
        </button>
        {capital && (
          <dl>
            <dt>Leverage</dt>
            <dd>{capital.leverage}</dd>
            <dt>Recommendation</dt>
            <dd>{capital.recommendation}</dd>
          </dl>
        )}
      </section>

      <section aria-label="Board pack approvals">
        <h2>Board pack approvals</h2>
        <p className="section-desc">
          The CFO gate: a synthesised board pack waits here before it can be published to the board.
          Click it to review the contents, then approve to release it or reject to hold it for
          revision — the pack is never published without the CFO&apos;s sign-off.
        </p>
        {approvals.length === 0 ? (
          <p>No board pack approvals</p>
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
