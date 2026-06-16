import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { RetailCommercialBankingPage } from './RetailCommercialBankingPage'

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
    const data = JSON.stringify({ job_id: 'job-b', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const fundApproval: Approval = {
  id: 'req-a1',
  tool_name: 'banking_fund_loan',
  actor: 'retail-commercial-banking',
  approver_role: 'underwriter',
  rationale: 'fund approved loan a1',
  state: 'pending',
  decided_by: null,
}

describe('RetailCommercialBankingPage', () => {
  it('renders the dashboard heading and regions', () => {
    render(<RetailCommercialBankingPage />)
    expect(
      screen.getByRole('heading', { name: /retail & commercial banking/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /lending pipeline/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /underwriter decisions/i })).toBeInTheDocument()
  })

  it('starts an application and greens the pipeline as stages finish', async () => {
    server.use(
      http.post('/agents/retail-commercial-banking/applications', () =>
        HttpResponse.json({ job_id: 'job-b' }),
      ),
    )

    render(<RetailCommercialBankingPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /start application/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-b/events')

    act(() => es.emit('underwriting', 'running'))
    const grid = screen.getByRole('region', { name: /lending pipeline/i })
    expect(await within(grid).findByTestId('step-underwriting')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('underwriting', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-underwriting')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('approves a held disbursement (underwriter decision)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [fundApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...fundApproval, state: 'approved', decided_by: 'sam' },
        })
      }),
    )

    render(<RetailCommercialBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /banking_fund_loan/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'sam')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no disbursements pending/i)).toBeInTheDocument())
  })

  it('rejects a held disbursement', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([fundApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...fundApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<RetailCommercialBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /banking_fund_loan/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'outside appetite')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<RetailCommercialBankingPage />)
    expect(await screen.findByText(/no disbursements pending/i)).toBeInTheDocument()
  })
})
