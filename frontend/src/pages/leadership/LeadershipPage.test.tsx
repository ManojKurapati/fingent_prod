import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { LeadershipPage } from './LeadershipPage'

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
    const data = JSON.stringify({ job_id: 'job-ld', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const publishApproval: Approval = {
  id: 'req-bp',
  tool_name: 'leadership_publish_board_pack',
  actor: 'leadership',
  approver_role: 'cfo',
  rationale: 'publish board pack for FY26',
  state: 'pending',
  decided_by: null,
}

describe('LeadershipPage', () => {
  it('renders the cockpit heading and regions', () => {
    render(<LeadershipPage />)
    expect(screen.getByRole('heading', { name: /executive cockpit/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /board pack synthesis/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /capital scenario sandbox/i })).toBeInTheDocument()
  })

  it('runs a board pack and turns the synthesis grid green as workers finish', async () => {
    server.use(
      http.post('/agents/leadership/board-pack', () => HttpResponse.json({ job_id: 'job-ld' })),
    )

    render(<LeadershipPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run board pack/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-ld/events')

    act(() => es.emit('capital-strategy', 'running'))
    const grid = screen.getByRole('region', { name: /board pack synthesis/i })
    expect(await within(grid).findByTestId('step-capital-strategy')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('capital-strategy', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-capital-strategy')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists the board-pack approval and approves it (CFO gate)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [publishApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...publishApproval, state: 'approved', decided_by: 'sam' },
        })
      }),
    )

    render(<LeadershipPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /leadership_publish_board_pack/i }),
    )

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'sam')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no board pack approvals/i)).toBeInTheDocument())
  })

  it('rejects a board-pack approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([publishApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...publishApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<LeadershipPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /leadership_publish_board_pack/i }),
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'need detail')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('runs a capital scenario and shows leverage vs recommendation', async () => {
    server.use(
      http.post('/agents/leadership/capital-scenario', () =>
        HttpResponse.json({ job_id: 'job-cap' }),
      ),
      http.get('/jobs/:id', () =>
        HttpResponse.json({
          id: 'job-cap',
          kind: 'leadership.capital_scenario',
          status: 'completed',
          attempts: 1,
          error: null,
          result: { 'capital-strategy': { leverage: 0.6, recommendation: 'raise_debt' } },
        }),
      ),
    )

    render(<LeadershipPage />)
    const sandbox = screen.getByRole('region', { name: /capital scenario sandbox/i })
    await userEvent.clear(within(sandbox).getByLabelText(/target leverage/i))
    await userEvent.type(within(sandbox).getByLabelText(/target leverage/i), '0.7')
    await userEvent.click(within(sandbox).getByRole('button', { name: /run capital scenario/i }))

    expect(await within(sandbox).findByText(/raise_debt/)).toBeInTheDocument()
    expect(within(sandbox).getByText(/0.6/)).toBeInTheDocument()
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<LeadershipPage />)
    expect(await screen.findByText(/no board pack approvals/i)).toBeInTheDocument()
  })
})
