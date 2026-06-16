import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { PrivateMarketsPage } from './PrivateMarketsPage'

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
    const data = JSON.stringify({ job_id: 'job-pm', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const commitApproval: Approval = {
  id: 'req-d1',
  tool_name: 'pm_commit_capital',
  actor: 'private-markets',
  approver_role: 'investment-committee',
  rationale: 'commit capital to d1 (IC approval gate)',
  state: 'pending',
  decided_by: null,
}

describe('PrivateMarketsPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<PrivateMarketsPage />)
    expect(screen.getByRole('heading', { name: /private markets/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /deal underwriting/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /portfolio monitor/i })).toBeInTheDocument()
  })

  it('underwrites a deal and greens the grid as workers finish', async () => {
    server.use(
      http.post('/agents/private-markets/deals', () => HttpResponse.json({ job_id: 'job-pm' })),
    )

    render(<PrivateMarketsPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /underwrite deal/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-pm/events')

    act(() => es.emit('credit-underwriting', 'running'))
    const grid = screen.getByRole('region', { name: /deal underwriting/i })
    expect(await within(grid).findByTestId('step-credit-underwriting')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('credit-underwriting', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-credit-underwriting')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('approves a held capital commitment (human IC vote)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [commitApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...commitApproval, state: 'approved', decided_by: 'ic' },
        })
      }),
    )

    render(<PrivateMarketsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /pm_commit_capital/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'ic')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no capital commitments pending/i)).toBeInTheDocument(),
    )
  })

  it('rejects a capital commitment', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([commitApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...commitApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<PrivateMarketsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /pm_commit_capital/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'needs more diligence')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('runs the portfolio monitor and shows covenant alerts', async () => {
    server.use(
      http.post('/agents/private-markets/monitor', () => HttpResponse.json({ job_id: 'job-mon' })),
      http.get('/jobs/:id', () =>
        HttpResponse.json({
          id: 'job-mon',
          kind: 'private-markets.monitor',
          status: 'completed',
          attempts: 1,
          error: null,
          result: { 'portfolio-stewardship': { monitored: true, alerts: ['covenant'] } },
        }),
      ),
    )

    render(<PrivateMarketsPage />)
    const monitor = screen.getByRole('region', { name: /portfolio monitor/i })
    await userEvent.click(within(monitor).getByRole('button', { name: /run monitor/i }))
    expect(await within(monitor).findByText(/alerts: covenant/i)).toBeInTheDocument()
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<PrivateMarketsPage />)
    expect(await screen.findByText(/no capital commitments pending/i)).toBeInTheDocument()
  })
})
