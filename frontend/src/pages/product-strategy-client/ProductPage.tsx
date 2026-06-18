// Product, Strategy & Client dashboard.
//
// The initiative path is shown as an SSE JobTimeline (discovery -> pricing ->
// filing-gate -> launch greening as it runs), with the ApprovalDrawer acting as
// the launch-approval gate. Launch is default-deny AND blocked until the
// compliance/regulatory-filing gate clears — an unfiled product never raises an
// approval at all.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApprovalDrawer } from '../../components/ApprovalDrawer'
import { JobTimeline } from '../../components/JobTimeline'
import { approveRequest, listApprovals, rejectRequest } from '../../lib/api'
import { subscribeJob } from '../../lib/sse'
import type { Approval, JobEvent } from '../../lib/types'
import { startInitiative } from './api'

type EventSourceImpl = Parameters<typeof subscribeJob>[2]

export interface ProductPageProps {
  // Injectable EventSource so the live grid is testable without a browser.
  eventSource?: EventSourceImpl
}

export function ProductPage({ eventSource }: ProductPageProps) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selected, setSelected] = useState<Approval | null>(null)
  const [name, setName] = useState('FX-Hedge')
  const [token, setToken] = useState('')
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const all = await listApprovals()
      setApprovals(all.filter((a) => a.tool_name.startsWith('product_')))
    } catch {
      setApprovals([])
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => unsubscribe.current?.()
  }, [refresh])

  const runInitiative = useCallback(async () => {
    setEvents([])
    const { job_id } = await startInitiative({ name, filing_token: token || null })
    unsubscribe.current?.()
    unsubscribe.current = subscribeJob(
      job_id,
      { onEvent: (event) => setEvents((prev) => [...prev, event]) },
      eventSource,
    )
  }, [eventSource, name, token])

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
    <div className="product-page">
      <header>
        <h1>Product, Strategy &amp; Client</h1>
      </header>

      <section aria-label="Product initiative">
        <h2>Initiative pipeline</h2>
        <p className="section-desc">
          Drives a product initiative through discovery → pricing → regulatory filing → launch. Name
          the product and paste the regulatory filing token if you have one, then run it: stages
          green as subagents finish. Launch is default-deny and stays blocked until the filing gate
          clears — without a valid filing token no launch approval is ever raised.
        </p>
        <div className="field-row">
          <label>
            Initiative name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="FX-Hedge"
            />
            <span className="field-hint">Working name of the product or initiative to run.</span>
          </label>
          <label>
            Filing token
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="FT-1"
            />
            <span className="field-hint">
              Regulatory filing reference; leave blank to keep launch blocked at the filing gate.
            </span>
          </label>
        </div>
        <button type="button" onClick={() => void runInitiative()}>
          Run initiative
        </button>
        <JobTimeline events={events} />
      </section>

      <section aria-label="Launch approvals">
        <h2>Launch approvals</h2>
        <p className="section-desc">
          This is the human-in-the-loop launch gate: a filed product waits here until a product
          owner decides. Click an item to review the launch rationale, then approve to take the
          product live or reject to hold it — nothing launches without sign-off.
        </p>
        {approvals.length === 0 ? (
          <p>No launches awaiting approval</p>
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
