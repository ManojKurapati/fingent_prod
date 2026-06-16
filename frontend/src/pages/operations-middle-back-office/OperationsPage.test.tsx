import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { OperationsPage } from './OperationsPage'

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
    const data = JSON.stringify({ job_id: 'job-ops', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const settlementApproval: Approval = {
  id: 'req-s1',
  tool_name: 'ops_instruct_settlement',
  actor: 'ops',
  approver_role: 'ops-controller',
  rationale: 'instruct settlement of 1000 for T1',
  state: 'pending',
  decided_by: null,
}

describe('OperationsPage', () => {
  it('renders the lifecycle and approvals regions', () => {
    render(<OperationsPage />)
    expect(
      screen.getByRole('heading', { name: /operations — middle & back office/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /trade lifecycle/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /settlement approvals/i })).toBeInTheDocument()
  })

  it('processes a trade and greens the lifecycle grid as workers finish', async () => {
    server.use(http.post('/agents/ops/process', () => HttpResponse.json({ job_id: 'job-ops' })))

    render(<OperationsPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /process trade/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-ops/events')

    act(() => es.emit('settlements', 'running'))
    const grid = screen.getByRole('region', { name: /trade lifecycle/i })
    expect(await within(grid).findByTestId('step-settlements')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('settlements', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-settlements')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists a settlement instruction and approves it (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [settlementApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...settlementApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<OperationsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /ops_instruct_settlement/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no settlement instructions/i)).toBeInTheDocument(),
    )
  })

  it('rejects a settlement instruction', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([settlementApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...settlementApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<OperationsPage />)
    await userEvent.click(await screen.findByRole('button', { name: /ops_instruct_settlement/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'mismatch')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<OperationsPage />)
    expect(await screen.findByText(/no settlement instructions/i)).toBeInTheDocument()
  })
})
