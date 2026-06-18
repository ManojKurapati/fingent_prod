// Tax workbench dashboard.
//
// Provision roll-forward / ETR bridge driven by the SSE JobTimeline (per-tax-type
// streams turn green as workers finish), a jurisdiction filing tracker, and the
// human-in-the-loop ApprovalDrawer gating every external filing.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, getJob, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { fileReturn, startProvision } from './api'

const PERIOD = 'FY26'
const JURISDICTIONS = ['US', 'UK']

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface TaxPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

interface Provision {
  current: number
  deferred: number
  total_tax: number
  etr: number
}

export function TaxPage({ eventSource }: TaxPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [provision, setProvision] = useState<Provision | null>(null)
  const [returnId, setReturnId] = useState('ret-US-2026')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('tax_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runProvision = useCallback(async () => {
    setEvents([])
    setProvision(null)
    const { job_id } = await startProvision({ period: PERIOD, jurisdictions: JURISDICTIONS })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      {
        onEvent: (event) => {
          setEvents((prev) => [...prev, event])
          if (event.payload.step === 'tax-provision' && event.payload.status === 'completed') {
            void getJob(job_id).then((job) => {
              const result = (job.result as Record<string, Provision> | null)?.['tax-provision']
              if (result) setProvision(result)
            })
          }
        },
      },
      eventSource,
    )
  }, [eventSource])

  const submitFiling = useCallback(async () => {
    await fileReturn(returnId, 'US')
    void refresh()
  }, [returnId, refresh])

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
    <div className="tax-page">
      <header>
        <h1>Tax Workbench</h1>
      </header>

      <section aria-label="Provision and ETR">
        <h2>Provision &amp; ETR</h2>
        <p className="section-desc">
          Runs the tax-provision roll-forward across jurisdictions for the period. Press Run
          provision and each tax-type stream turns green as its subagent finishes; when complete it
          shows current and deferred tax and the resulting effective tax rate (ETR).
        </p>
        <button type="button" onClick={() => void runProvision()}>
          Run provision
        </button>
        <JobTimeline events={events} />
        {provision && (
          <dl>
            <dt>Current</dt>
            <dd>{provision.current}</dd>
            <dt>Deferred</dt>
            <dd>{provision.deferred}</dd>
            <dt>ETR</dt>
            <dd>{(provision.etr * 100).toFixed(1)}%</dd>
          </dl>
        )}
      </section>

      <section aria-label="Filing tracker">
        <h2>Filing tracker</h2>
        <p className="section-desc">
          Submits a prepared tax return for filing. Enter the return reference and press File return
          to raise it — because a filing is an external, consequential action it does not file
          immediately; it surfaces as a filing approval below and is only filed once approved.
        </p>
        <label>
          Return ID
          <input
            value={returnId}
            onChange={(e) => setReturnId(e.target.value)}
            placeholder="ret-US-2026"
          />
          <span className="field-hint">Identifier of the prepared return, e.g. ret-US-2026.</span>
        </label>
        <button type="button" onClick={() => void submitFiling()}>
          File return
        </button>
      </section>

      <section aria-label="Filing approvals">
        <h2>Filing approvals</h2>
        <p className="section-desc">
          A human-in-the-loop gate for external filings: returns wait here until the head of tax
          signs off. Click an item to review the return and rationale, then approve to file it with
          the authority or reject to hold — nothing is filed without approval.
        </p>
        {approvals.length === 0 ? (
          <p>No filing approvals</p>
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
