import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { AuditPage } from './AuditPage'

// A fake EventSource we can drive from the test (jsdom has none).
class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onerror: ((ev: unknown) => void) | null = null
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {}
  closed = false
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, cb: (ev: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(cb)
  }
  emit(step: string, status: string) {
    const data = JSON.stringify({ job_id: 'job-aud', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const auditApproval: Approval = {
  id: 'req-pub',
  tool_name: 'audit_publish_findings',
  actor: 'audit',
  approver_role: 'cae',
  rationale: 'issue audit report for FY26-rev (2 findings)',
  state: 'pending',
  decided_by: null,
}

describe('AuditPage', () => {
  it('renders the assurance dashboard heading and regions', () => {
    render(<AuditPage />)
    expect(screen.getByRole('heading', { name: /internal audit/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /control testing/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /findings/i })).toBeInTheDocument()
  })

  it('runs an engagement and turns the control-testing grid green', async () => {
    server.use(
      http.post('/agents/audit/engagement', () => HttpResponse.json({ job_id: 'job-aud' })),
    )

    render(<AuditPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run engagement/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-aud/events')

    act(() => es.emit('control-test:c1', 'running'))
    const grid = screen.getByRole('region', { name: /control testing/i })
    expect(await within(grid).findByTestId('step-control-test:c1')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('control-test:c1', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-control-test:c1')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists the report-issuance approval and approves it (CAE gate)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [auditApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...auditApproval, state: 'approved', decided_by: 'cae-jo' },
        })
      }),
    )

    render(<AuditPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /audit_publish_findings/i }),
    )

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'cae-jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no report awaiting issuance/i)).toBeInTheDocument())
  })

  it('rejects a report-issuance approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([auditApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...auditApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<AuditPage />)
    await userEvent.click(await screen.findByRole('button', { name: /audit_publish_findings/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'need detail')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<AuditPage />)
    expect(await screen.findByText(/no report awaiting issuance/i)).toBeInTheDocument()
  })
})
