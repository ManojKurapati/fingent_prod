import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { QuantPage } from './QuantPage'

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
    const data = JSON.stringify({ job_id: 'job-q', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const promoteApproval: Approval = {
  id: 'req-p1',
  tool_name: 'quant_promote_model',
  actor: 'quant',
  approver_role: 'head-of-quant',
  rationale: 'promote validated model M1 to production',
  state: 'pending',
  decided_by: null,
}

describe('QuantPage', () => {
  it('renders the research and promotion regions', () => {
    render(<QuantPage />)
    expect(
      screen.getByRole('heading', { name: /quantitative, data & technology/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /research fan-out/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /promote to production/i })).toBeInTheDocument()
  })

  it('runs research and greens a workstream as it finishes', async () => {
    server.use(http.post('/agents/quant/jobs', () => HttpResponse.json({ job_id: 'job-q' })))

    render(<QuantPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run research/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-q/events')

    act(() => es.emit('quant-research', 'completed'))
    const grid = screen.getByRole('region', { name: /research fan-out/i })
    await waitFor(() =>
      expect(within(grid).getByTestId('step-quant-research')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('submits a promotion request behind the validation gate', async () => {
    let body: unknown = null
    server.use(
      http.post('/agents/quant/promote', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-promote' })
      }),
    )

    render(<QuantPage />)
    const region = screen.getByRole('region', { name: /promote to production/i })
    await userEvent.type(within(region).getByLabelText(/validation token/i), 'VT-1')
    await userEvent.click(within(region).getByRole('button', { name: /promote/i }))

    await waitFor(() => expect(body).toEqual({ model_id: 'M1', validation_token: 'VT-1' }))
  })

  it('lists a promotion approval and approves it (promote-to-production gate)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [promoteApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...promoteApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<QuantPage />)
    await userEvent.click(await screen.findByRole('button', { name: /quant_promote_model/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no promotions awaiting approval/i)).toBeInTheDocument())
  })

  it('rejects a promotion approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([promoteApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...promoteApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<QuantPage />)
    await userEvent.click(await screen.findByRole('button', { name: /quant_promote_model/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'needs revalidation')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<QuantPage />)
    expect(await screen.findByText(/no promotions awaiting approval/i)).toBeInTheDocument()
  })
})
