// Quantitative, Data & Technology dashboard.
//
// A model/strategy registry: the SSE JobTimeline shows the parallel research
// fan-out greening as the six workstreams finish, and the ApprovalDrawer is the
// promote-to-production gate. Promotion is default-deny AND blocked unless an
// independent model-validation token (from the Risk Agent) clears — a candidate
// with no validation token never raises an approval at all.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startPromote, startResearch } from './api'

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface QuantPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function QuantPage({ eventSource }: QuantPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [modelId, setModelId] = useState('M1')
  const [token, setToken] = useState('')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('quant_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runResearch = useCallback(async () => {
    setEvents([])
    const { job_id } = await startResearch({ dataset: 'eod-prices' })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const runPromote = useCallback(async () => {
    await startPromote({ model_id: modelId, validation_token: token || null })
    void refresh()
  }, [modelId, token, refresh])

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
    <div className="quant-page">
      <header>
        <h1>Quantitative, Data &amp; Technology</h1>
      </header>

      <section aria-label="Research fan-out">
        <h2>Research workstreams</h2>
        <p className="section-desc">
          Kick off the parallel quant research fan-out across the six workstreams. Run it and the
          timeline greens as each workstream finishes — this is read-only research that produces
          candidate models; nothing reaches production from here until it is promoted and approved
          below.
        </p>
        <button type="button" onClick={() => void runResearch()}>
          Run research
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Promote to production">
        <h2>Promote model</h2>
        <p className="section-desc">
          Request promotion of a candidate model to production. Enter the model id and paste the
          independent model-validation token issued by the Risk Agent, then promote: promotion is
          default-deny and is blocked unless that token clears, so a candidate with no valid token
          never raises an approval. Cleared requests appear below for a head-of-quant sign-off before
          anything goes live.
        </p>
        <div className="field-row">
          <label>
            Model id
            <input
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder="M1"
            />
            <span className="field-hint">Registry id of the candidate model to promote.</span>
          </label>
          <label>
            Validation token
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="VT-1"
            />
            <span className="field-hint">
              Independent validation token from the Risk Agent; leave blank if none (promotion will
              be blocked).
            </span>
          </label>
        </div>
        <button type="button" onClick={() => void runPromote()}>
          Promote
        </button>
      </section>

      <section aria-label="Promotion approvals">
        <h2>Promotion approvals</h2>
        <p className="section-desc">
          These are the human-in-the-loop promote-to-production gates. Each item is a validated model
          waiting on a head-of-quant sign-off. Click one to review the rationale, then approve to
          promote it to production or reject to send it back — no model goes live without an approval
          here.
        </p>
        {approvals.length === 0 ? (
          <p>No promotions awaiting approval</p>
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
