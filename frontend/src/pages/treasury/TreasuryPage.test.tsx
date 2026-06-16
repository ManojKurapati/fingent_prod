import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { TreasuryPage } from './TreasuryPage'

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
    const data = JSON.stringify({ job_id: 'job-tr', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const hedgeApproval: Approval = {
  id: 'req-hedge',
  tool_name: 'treasury_execute_hedge',
  actor: 'treasury',
  approver_role: 'treasurer',
  rationale: 'execute FX hedge EURUSD notional 500',
  state: 'pending',
  decided_by: null,
}

describe('TreasuryPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<TreasuryPage />)
    expect(screen.getByRole('heading', { name: /treasury/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /daily position/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /^cash movement$/i })).toBeInTheDocument()
  })

  it('runs the daily position and streams the spine as workers finish', async () => {
    server.use(
      http.post('/agents/treasury/daily-position', () => HttpResponse.json({ job_id: 'job-tr' })),
      http.get('/approvals', () => HttpResponse.json([])),
    )

    render(<TreasuryPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run daily position/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-tr/events')

    act(() => es.emit('liquidity-forecasting', 'running'))
    const grid = screen.getByRole('region', { name: /daily position/i })
    expect(await within(grid).findByTestId('step-liquidity-forecasting')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('liquidity-forecasting', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-liquidity-forecasting')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('submits a gated hedge execution and surfaces it for approval', async () => {
    let submitted = false
    server.use(
      http.post('/agents/treasury/hedge/execute', () => {
        submitted = true
        return HttpResponse.json({ executed: false, approval_id: 'req-hedge' })
      }),
      http.get('/approvals', () => HttpResponse.json(submitted ? [hedgeApproval] : [])),
    )

    render(<TreasuryPage />)
    await userEvent.click(screen.getByRole('button', { name: /execute hedge/i }))

    expect(submitted).toBe(true)
    await userEvent.click(
      await screen.findByRole('button', { name: /treasury_execute_hedge/i }),
    )
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
  })

  it('approves a held cash movement (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [hedgeApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...hedgeApproval, state: 'approved', decided_by: 'lee' },
        })
      }),
    )

    render(<TreasuryPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /treasury_execute_hedge/i }),
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'lee')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no cash movements awaiting approval/i)).toBeInTheDocument(),
    )
  })

  it('rejects a held cash movement', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([hedgeApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...hedgeApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<TreasuryPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /treasury_execute_hedge/i }),
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'outside policy')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('submits a gated sweep', async () => {
    let swept = false
    server.use(
      http.post('/agents/treasury/sweep', () => {
        swept = true
        return HttpResponse.json({ executed: false, approval_id: 'req-sweep' })
      }),
      http.get('/approvals', () => HttpResponse.json([])),
    )

    render(<TreasuryPage />)
    await userEvent.click(screen.getByRole('button', { name: /sweep cash/i }))
    await waitFor(() => expect(swept).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<TreasuryPage />)
    expect(await screen.findByText(/no cash movements awaiting approval/i)).toBeInTheDocument()
  })
})
