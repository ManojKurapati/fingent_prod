import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { AssetManagementPage } from './AssetManagementPage'

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
    const data = JSON.stringify({ job_id: 'job-aim', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const placeApproval: Approval = {
  id: 'req-pf1',
  tool_name: 'aim_place_orders',
  actor: 'asset-investment-management',
  approver_role: 'portfolio-manager',
  rationale: 'place rebalance orders for pf1',
  state: 'pending',
  decided_by: null,
}

describe('AssetManagementPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<AssetManagementPage />)
    expect(
      screen.getByRole('heading', { name: /asset & investment management/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /rebalance/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /trade approvals/i })).toBeInTheDocument()
  })

  it('runs a rebalance and greens the timeline through the gate', async () => {
    server.use(
      http.post('/agents/asset-investment-management/rebalance', () =>
        HttpResponse.json({ job_id: 'job-aim' }),
      ),
    )

    render(<AssetManagementPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run rebalance/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-aim/events')

    act(() => es.emit('mandate-risk-gate', 'running'))
    const grid = screen.getByRole('region', { name: /rebalance/i })
    expect(await within(grid).findByTestId('step-mandate-risk-gate')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('mandate-risk-gate', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-mandate-risk-gate')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('runs a standalone research fan-out', async () => {
    server.use(
      http.post('/agents/asset-investment-management/research', () =>
        HttpResponse.json({ job_id: 'job-research' }),
      ),
    )

    render(<AssetManagementPage />)
    await userEvent.click(screen.getByRole('button', { name: /run research/i }))
    expect(await screen.findByText(/research job: job-research/i)).toBeInTheDocument()
  })

  it('lists and approves order placement (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [placeApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...placeApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<AssetManagementPage />)
    await userEvent.click(await screen.findByRole('button', { name: /aim_place_orders/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no trade approvals pending/i)).toBeInTheDocument())
  })

  it('rejects an order-placement approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([placeApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...placeApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<AssetManagementPage />)
    await userEvent.click(await screen.findByRole('button', { name: /aim_place_orders/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'over limit')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<AssetManagementPage />)
    expect(await screen.findByText(/no trade approvals pending/i)).toBeInTheDocument()
  })
})
