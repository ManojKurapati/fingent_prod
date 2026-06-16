// Corp Dev & Strategy deal room + IR console.
//
// Pulls together the shared platform primitives: a live deal-evaluation grid driven
// by the SSE JobTimeline (steps turn green as workers finish), an earnings-pack
// trigger for the standing/IR lanes, and the human-in-the-loop ApprovalDrawer for
// the board gate (deal recommendation) and Reg FD gate (earnings publication).

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startDeal, startEarningsPack } from './api'

const TARGETS = ['alpha', 'beta', 'gamma']
const PERIOD = 'Q1FY26'
const SEGMENTS = ['saas', 'fintech']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface CorpDevPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function CorpDevPage({ eventSource }: CorpDevPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('corpdev_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const subscribe = useCallback(
    (jobId: string) => {
      unsubscribe.current?.()
      unsubscribe.current = subscribeJob(
        jobId,
        { onEvent: (event) => setEvents((prev) => [...prev, event]) },
        eventSource,
      )
    },
    [eventSource],
  )

  const runDeal = useCallback(async () => {
    setEvents([])
    const { job_id } = await startDeal({
      targets: TARGETS,
      synergy_rate: 0.1,
      ebitda_multiple: 8.0,
    })
    subscribe(job_id)
  }, [subscribe])

  const runEarnings = useCallback(async () => {
    setEvents([])
    const { job_id } = await startEarningsPack({ period: PERIOD, segments: SEGMENTS })
    subscribe(job_id)
  }, [subscribe])

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
    <div className="corpdev-page">
      <header>
        <h1>Deal Room</h1>
      </header>

      <section aria-label="Deal evaluation">
        <h2>Deal evaluation</h2>
        <button type="button" onClick={() => void runDeal()}>
          Run deal
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="IR console">
        <h2>IR console</h2>
        <button type="button" onClick={() => void runEarnings()}>
          Run earnings pack
        </button>
      </section>

      <section aria-label="Disclosure approvals">
        <h2>Disclosure approvals</h2>
        {approvals.length === 0 ? (
          <p>No disclosure approvals</p>
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
