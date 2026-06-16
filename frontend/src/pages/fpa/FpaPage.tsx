// FP&A planning dashboard — the reference page wave 2/3 group dashboards copy.
//
// Pulls together the shared platform primitives: a live variance grid driven by
// the SSE JobTimeline (cost-centre rows turn green as workers finish), a scenario
// sandbox, and the human-in-the-loop ApprovalDrawer for variance commentary.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, getJob, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startForecast, startScenario } from './api'

const PERIOD = 'FY26'
const COST_CENTRES = ['cc1', 'cc2', 'cc3', 'cc4']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface FpaPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

interface ScenarioResult {
  base: number
  adjusted: number
}

export function FpaPage({ eventSource }: FpaPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [driver, setDriver] = useState('0.05')
  const [scenario, setScenario] = useState<ScenarioResult | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('fpa_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runForecast = useCallback(async () => {
    setEvents([])
    const { job_id } = await startForecast({
      period: PERIOD,
      cost_centres: COST_CENTRES,
      variance_threshold: 0.1,
    })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      {
        onEvent: (event) => {
          setEvents((prev) => [...prev, event])
          // When the run finishes, any commentary request is now in the queue.
          if (event.type === 'status') void refresh()
        },
      },
      eventSource,
    )
  }, [eventSource, refresh])

  const runScenario = useCallback(async () => {
    const { job_id } = await startScenario({
      period: PERIOD,
      cost_centres: COST_CENTRES,
      drivers: { price: Number(driver) || 0 },
    })
    const job = await getJob(job_id)
    const result = (job.result as Record<string, ScenarioResult> | null)?.['scenario-modelling']
    if (result) setScenario({ base: result.base, adjusted: result.adjusted })
  }, [driver])

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
    <div className="fpa-page">
      <header>
        <h1>FP&amp;A Planning</h1>
      </header>

      <section aria-label="Live variance grid">
        <h2>Variance by cost centre</h2>
        <button type="button" onClick={() => void runForecast()}>
          Run forecast
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Scenario sandbox">
        <h2>Scenario sandbox</h2>
        <label>
          Driver (price delta)
          <input
            type="number"
            step="0.01"
            value={driver}
            onChange={(e) => setDriver(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => void runScenario()}>
          Run scenario
        </button>
        {scenario && (
          <dl>
            <dt>Base</dt>
            <dd>{scenario.base}</dd>
            <dt>Adjusted</dt>
            <dd>{scenario.adjusted}</dd>
          </dl>
        )}
      </section>

      <section aria-label="Commentary requests">
        <h2>Variance commentary requests</h2>
        {approvals.length === 0 ? (
          <p>No commentary requests</p>
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
