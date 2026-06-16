import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { InvestmentBankingPage } from './InvestmentBankingPage'

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
    const data = JSON.stringify({ job_id: 'job-ib', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const launchApproval: Approval = {
  id: 'req-d1',
  tool_name: 'ib_launch_mandate',
  actor: 'investment-banking',
  approver_role: 'compliance',
  rationale: 'ma-execution launch for acme',
  state: 'pending',
  decided_by: null,
}

describe('InvestmentBankingPage', () => {
  it('renders the deal workspace heading and regions', () => {
    render(<InvestmentBankingPage />)
    expect(screen.getByRole('heading', { name: /investment banking/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /deal mandate/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /wall-crossing/i })).toBeInTheDocument()
  })

  it('runs a mandate and greens the timeline as subagents finish', async () => {
    server.use(
      http.post('/agents/investment-banking/mandates', () =>
        HttpResponse.json({ job_id: 'job-ib' }),
      ),
    )

    render(<InvestmentBankingPage eventSource={FakeEventSource as never} />)
    await userEvent.selectOptions(screen.getByLabelText(/deal type/i), 'ecm')
    await userEvent.click(screen.getByRole('button', { name: /run mandate/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-ib/events')

    act(() => es.emit('compliance-gate', 'running'))
    const grid = screen.getByRole('region', { name: /deal mandate/i })
    expect(await within(grid).findByTestId('step-compliance-gate')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('compliance-gate', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-compliance-gate')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists and approves the wall-crossing launch (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [launchApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...launchApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<InvestmentBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /ib_launch_mandate/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no launch approvals pending/i)).toBeInTheDocument(),
    )
  })

  it('rejects a launch approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([launchApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...launchApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<InvestmentBankingPage />)
    await userEvent.click(await screen.findByRole('button', { name: /ib_launch_mandate/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'conflict unresolved')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<InvestmentBankingPage />)
    expect(await screen.findByText(/no launch approvals pending/i)).toBeInTheDocument()
  })
})
