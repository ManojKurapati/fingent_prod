// Live subagent timeline — FROZEN CONTRACT (props shape).
//
// Renders the streaming DAG of subagents for a job: one row per step with its
// latest status, so a variance grid can turn green as workers finish.

import type { JobEvent } from '../lib/types'

export interface JobTimelineProps {
  events: JobEvent[]
}

interface StepRow {
  step: string
  status: string
}

function toRows(events: JobEvent[]): StepRow[] {
  const order: string[] = []
  const latest = new Map<string, string>()
  for (const ev of events) {
    if (ev.type !== 'step') continue
    const step = String(ev.payload.step ?? '')
    const status = String(ev.payload.status ?? 'queued')
    if (!latest.has(step)) order.push(step)
    latest.set(step, status)
  }
  return order.map((step) => ({ step, status: latest.get(step) ?? 'queued' }))
}

export function JobTimeline({ events }: JobTimelineProps) {
  const rows = toRows(events)

  if (rows.length === 0) {
    return <p className="job-timeline-empty">No activity yet</p>
  }

  return (
    <ol className="job-timeline" aria-label="Subagent timeline">
      {rows.map((row) => (
        <li key={row.step} data-testid={`step-${row.step}`} data-status={row.status}>
          <span className="step-name">{row.step}</span>
          <span className="step-status">{row.status}</span>
        </li>
      ))}
    </ol>
  )
}
