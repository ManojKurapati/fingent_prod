import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { TransactionalPage } from './TransactionalPage'

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
    const data = JSON.stringify({ job_id: 'job-tx', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const paymentApproval: Approval = {
  id: 'req-v1',
  tool_name: 'transactional_execute_payment',
  actor: 'transactional',
  approver_role: 'treasurer',
  rationale: 'AP payment run of 500 across 1 vendors',
  state: 'pending',
  decided_by: null,
}

describe('TransactionalPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<TransactionalPage />)
    expect(screen.getByRole('heading', { name: /operational finance/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /operational cycle/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /payment approvals/i })).toBeInTheDocument()
  })

  it('runs the cycle and turns the lane grid green as workers finish', async () => {
    server.use(
      http.post('/agents/transactional/cycle/run', () => HttpResponse.json({ job_id: 'job-tx' })),
    )

    render(<TransactionalPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run cycle/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-tx/events')

    act(() => es.emit('billing', 'running'))
    const grid = screen.getByRole('region', { name: /operational cycle/i })
    expect(await within(grid).findByTestId('step-billing')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('billing', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-billing')).toHaveAttribute('data-status', 'completed'),
    )
  })

  it('starts an AP payment run', async () => {
    let started = false
    server.use(
      http.post('/agents/transactional/ap/run', () => {
        started = true
        return HttpResponse.json({ job_id: 'job-ap' })
      }),
    )
    render(<TransactionalPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run ap payment run/i }))
    await waitFor(() => expect(started).toBe(true))
  })

  it('lists a cash-movement approval and approves it (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [paymentApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...paymentApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<TransactionalPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /transactional_execute_payment/i }),
    )

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no payment approvals/i)).toBeInTheDocument())
  })

  it('rejects a cash-movement approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([paymentApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...paymentApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<TransactionalPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /transactional_execute_payment/i }),
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'verify beneficiaries')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<TransactionalPage />)
    expect(await screen.findByText(/no payment approvals/i)).toBeInTheDocument()
  })
})
