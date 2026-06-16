import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { SalesTradingPage } from './SalesTradingPage'

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
    const data = JSON.stringify({ job_id: 'job-stm', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const routeApproval: Approval = {
  id: 'req-o1',
  tool_name: 'markets_route_order',
  actor: 'sales-trading-markets',
  approver_role: 'trader',
  rationale: 'route order o1 (notional 50)',
  state: 'pending',
  decided_by: null,
}

describe('SalesTradingPage', () => {
  it('renders the desk blotter heading and regions', () => {
    render(<SalesTradingPage />)
    expect(screen.getByRole('heading', { name: /sales & trading/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /desk blotter/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /routing approvals/i })).toBeInTheDocument()
  })

  it('submits an order and greens the timeline through the risk gate', async () => {
    server.use(
      http.post('/agents/sales-trading-markets/orders', () =>
        HttpResponse.json({ job_id: 'job-stm' }),
      ),
    )

    render(<SalesTradingPage eventSource={FakeEventSource as never} />)
    await userEvent.selectOptions(screen.getByLabelText(/side/i), 'sell')
    await userEvent.click(screen.getByRole('button', { name: /submit order/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-stm/events')

    act(() => es.emit('pre-trade-risk-gate', 'running'))
    const grid = screen.getByRole('region', { name: /desk blotter/i })
    expect(await within(grid).findByTestId('step-pre-trade-risk-gate')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('pre-trade-risk-gate', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-pre-trade-risk-gate')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists and approves order routing (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [routeApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...routeApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<SalesTradingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /markets_route_order/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no routing approvals pending/i)).toBeInTheDocument(),
    )
  })

  it('rejects an order-routing approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([routeApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...routeApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<SalesTradingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /markets_route_order/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'limit breach')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<SalesTradingPage />)
    expect(await screen.findByText(/no routing approvals pending/i)).toBeInTheDocument()
  })
})
