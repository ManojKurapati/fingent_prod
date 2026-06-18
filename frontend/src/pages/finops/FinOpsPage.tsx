// Finance Systems & Operations console.
//
// A live data-pipeline grid driven by the SSE JobTimeline (stages turn green as
// workers finish), an ERP access-change request form, and the human-in-the-loop
// ApprovalDrawer for the segregation-of-duties gate (SoD review before any
// conflicting access change is applied).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startAccessChange, startPipelineRun } from './api'

const PERIOD = 'FY26'
const SOURCES = ['gl', 'ap', 'ar']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface FinOpsPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function FinOpsPage({ eventSource }: FinOpsPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [change, setChange] = useState('')
  const [role, setRole] = useState('')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('finops_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runPipeline = useCallback(async () => {
    setEvents([])
    const { job_id } = await startPipelineRun({ period: PERIOD, sources: SOURCES })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

  const requestAccessChange = useCallback(async () => {
    await startAccessChange({ change, role })
    setChange('')
    setRole('')
    void refresh()
  }, [change, role, refresh])

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
    <div className="finops-page">
      <header>
        <h1>Finance Systems &amp; Operations</h1>
      </header>

      <section aria-label="Data pipeline health">
        <h2>Data pipeline</h2>
        <p className="section-desc">
          Runs the finance data pipeline that loads and reconciles the source ledgers (GL, AP, AR) for
          the period; each stage turns green as a worker finishes. This is read-only ingestion — it
          surfaces pipeline health and does not change any ERP records.
        </p>
        <button type="button" onClick={() => void runPipeline()}>
          Run pipeline
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="ERP access changes">
        <h2>ERP access changes</h2>
        <p className="section-desc">
          Request a change to someone&apos;s ERP access. Enter the change and the role it targets, then
          submit: any request that creates a segregation-of-duties conflict is held in the queue below
          for a SoD reviewer to approve before it is applied — nothing is granted automatically.
        </p>
        <div className="field-row">
          <label>
            Change
            <input
              value={change}
              onChange={(e) => setChange(e.target.value)}
              placeholder="grant-admin"
            />
            <span className="field-hint">The access change to make, e.g. grant-admin.</span>
          </label>
          <label>
            Role
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="superuser"
            />
            <span className="field-hint">The ERP role being modified, e.g. superuser.</span>
          </label>
        </div>
        <button type="button" onClick={() => void requestAccessChange()}>
          Request access change
        </button>
        {approvals.length === 0 ? (
          <p>No access changes pending review</p>
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
