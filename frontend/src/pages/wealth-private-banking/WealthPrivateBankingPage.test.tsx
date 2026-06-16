import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { WealthPrivateBankingPage } from './WealthPrivateBankingPage'

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
    const data = JSON.stringify({ job_id: 'job-w', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const rebalanceApproval: Approval = {
  id: 'req-c1',
  tool_name: 'wealth_rebalance',
  actor: 'wealth-private-banking',
  approver_role: 'advisor',
  rationale: 'rebalance discretionary book for c1',
  state: 'pending',
  decided_by: null,
}

describe('WealthPrivateBankingPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<WealthPrivateBankingPage />)
    expect(screen.getByRole('heading', { name: /wealth & private banking/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /client onboarding/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /suitability actions/i })).toBeInTheDocument()
  })

  it('onboards a client and greens the grid as workers finish', async () => {
    server.use(
      http.post('/agents/wealth-private-banking/clients', () =>
        HttpResponse.json({ job_id: 'job-w' }),
      ),
    )

    render(<WealthPrivateBankingPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /onboard client/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-w/events')

    act(() => es.emit('client-onboarding-kyc', 'running'))
    const grid = screen.getByRole('region', { name: /client onboarding/i })
    expect(await within(grid).findByTestId('step-client-onboarding-kyc')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('client-onboarding-kyc', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-client-onboarding-kyc')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('proposes a rebalance and surfaces it for suitability sign-off', async () => {
    let posted = false
    server.use(
      http.post('/agents/wealth-private-banking/rebalance', () => {
        posted = true
        return HttpResponse.json({ job_id: 'job-rb' })
      }),
      http.get('/approvals', () => HttpResponse.json(posted ? [rebalanceApproval] : [])),
    )

    render(<WealthPrivateBankingPage />)
    await userEvent.click(screen.getByRole('button', { name: /propose rebalance/i }))
    expect(posted).toBe(true)
    await screen.findByRole('button', { name: /wealth_rebalance/i })
  })

  it('proposes a Lombard facility', async () => {
    let posted = false
    server.use(
      http.post('/agents/wealth-private-banking/credit', () => {
        posted = true
        return HttpResponse.json({ job_id: 'job-cr' })
      }),
    )

    render(<WealthPrivateBankingPage />)
    await userEvent.click(screen.getByRole('button', { name: /propose lombard facility/i }))
    await waitFor(() => expect(posted).toBe(true))
  })

  it('approves a held rebalance (suitability sign-off)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [rebalanceApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...rebalanceApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<WealthPrivateBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /wealth_rebalance/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no actions pending sign-off/i)).toBeInTheDocument())
  })

  it('rejects a held rebalance', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([rebalanceApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...rebalanceApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<WealthPrivateBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /wealth_rebalance/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'unsuitable risk')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<WealthPrivateBankingPage />)
    expect(await screen.findByText(/no actions pending sign-off/i)).toBeInTheDocument()
  })
})
