import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { FinOpsPage } from './FinOpsPage'

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
    const data = JSON.stringify({ job_id: 'job-fin', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const sodApproval: Approval = {
  id: 'req-sod',
  tool_name: 'finops_access_change',
  actor: 'finops',
  approver_role: 'sod-reviewer',
  rationale: "access change 'grant-admin' introduces a segregation-of-duties conflict",
  state: 'pending',
  decided_by: null,
}

describe('FinOpsPage', () => {
  it('renders the operations console heading and regions', () => {
    render(<FinOpsPage />)
    expect(screen.getByRole('heading', { name: /finance systems/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /pipeline/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /access changes/i })).toBeInTheDocument()
  })

  it('runs the pipeline and turns the data-pipeline grid green', async () => {
    server.use(
      http.post('/agents/finops/pipeline/run', () => HttpResponse.json({ job_id: 'job-fin' })),
    )

    render(<FinOpsPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run pipeline/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-fin/events')

    act(() => es.emit('data-pipelines', 'running'))
    const grid = screen.getByRole('region', { name: /pipeline/i })
    expect(await within(grid).findByTestId('step-data-pipelines')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('data-pipelines', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-data-pipelines')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('submits a standalone access change request', async () => {
    let body: unknown = null
    server.use(
      http.post('/agents/finops/erp/access-change', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-acc' })
      }),
    )

    render(<FinOpsPage />)
    const region = screen.getByRole('region', { name: /access changes/i })
    await userEvent.type(within(region).getByLabelText(/change/i), 'grant-admin')
    await userEvent.type(within(region).getByLabelText(/role/i), 'superuser')
    await userEvent.click(within(region).getByRole('button', { name: /request access change/i }))

    await waitFor(() => expect(body).toEqual({ change: 'grant-admin', role: 'superuser' }))
  })

  it('lists the SoD approval and approves it (SoD review gate)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [sodApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...sodApproval, state: 'approved', decided_by: 'sod-jo' },
        })
      }),
    )

    render(<FinOpsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /finops_access_change/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'sod-jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no access changes pending/i)).toBeInTheDocument())
  })

  it('rejects a SoD approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([sodApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...sodApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<FinOpsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /finops_access_change/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'segregation risk')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<FinOpsPage />)
    expect(await screen.findByText(/no access changes pending/i)).toBeInTheDocument()
  })
})
