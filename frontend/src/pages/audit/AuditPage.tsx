// Internal Audit & Controls assurance dashboard.
//
// A live control-testing grid driven by the SSE JobTimeline (control rows turn
// green as test workers finish), plus the human-in-the-loop ApprovalDrawer for the
// report-issuance gate (CAE approval before any audit report is published).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startEngagement } from './api'

const ENGAGEMENT = 'FY26-rev'
const CONTROLS = ['c1', 'c2', 'c3', 'c4']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface AuditPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function AuditPage({ eventSource }: AuditPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('audit_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runEngagement = useCallback(async () => {
    setEvents([])
    const { job_id } = await startEngagement({ engagement: ENGAGEMENT, controls: CONTROLS })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource])

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
    <div className="audit-page">
      <header>
        <h1>Internal Audit &amp; Controls</h1>
      </header>

      <section aria-label="Control testing">
        <h2>Control testing</h2>
        <p className="section-desc">
          Runs the audit engagement, fanning out automated test workers across each control in scope;
          rows turn green as tests finish. Any failed controls become findings that feed the report
          below, which can only be issued after CAE approval.
        </p>
        <button type="button" onClick={() => void runEngagement()}>
          Run engagement
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Findings &amp; report issuance">
        <h2>Findings &amp; report issuance</h2>
        <p className="section-desc">
          The CAE gate: once an engagement&apos;s findings are compiled, the audit report waits here for
          issuance. Click it to review the findings, then approve to publish the report or reject to
          hold it for revision — no report is issued without the CAE&apos;s sign-off.
        </p>
        {approvals.length === 0 ? (
          <p>No report awaiting issuance</p>
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
