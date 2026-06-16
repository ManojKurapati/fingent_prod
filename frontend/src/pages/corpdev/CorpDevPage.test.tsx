import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { CorpDevPage } from './CorpDevPage'

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
    const data = JSON.stringify({ job_id: 'job-deal', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const dealApproval: Approval = {
  id: 'req-deal',
  tool_name: 'corpdev_publish_deal',
  actor: 'corpdev',
  approver_role: 'board',
  rationale: "deal recommendation 'proceed' for beta",
  state: 'pending',
  decided_by: null,
}

describe('CorpDevPage', () => {
  it('renders the deal room heading and regions', () => {
    render(<CorpDevPage />)
    expect(screen.getByRole('heading', { name: /deal room/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /deal evaluation/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /ir console/i })).toBeInTheDocument()
  })

  it('runs a deal and turns the evaluation grid green as workers finish', async () => {
    server.use(http.post('/agents/corpdev/deal', () => HttpResponse.json({ job_id: 'job-deal' })))

    render(<CorpDevPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run deal/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-deal/events')

    act(() => es.emit('valuation-modelling', 'running'))
    const grid = screen.getByRole('region', { name: /deal evaluation/i })
    expect(await within(grid).findByTestId('step-valuation-modelling')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('valuation-modelling', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-valuation-modelling')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('runs the earnings pack (standing/IR lanes) and subscribes', async () => {
    server.use(
      http.post('/agents/corpdev/ir/earnings-pack', () =>
        HttpResponse.json({ job_id: 'job-deal' }),
      ),
    )

    render(<CorpDevPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run earnings pack/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-deal/events')
  })

  it('lists the deal-recommendation approval and approves it (board gate)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [dealApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...dealApproval, state: 'approved', decided_by: 'chair' },
        })
      }),
    )

    render(<CorpDevPage />)
    await userEvent.click(await screen.findByRole('button', { name: /corpdev_publish_deal/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'chair')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no disclosure approvals/i)).toBeInTheDocument())
  })

  it('rejects a deal-recommendation approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([dealApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...dealApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<CorpDevPage />)
    await userEvent.click(await screen.findByRole('button', { name: /corpdev_publish_deal/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'price too high')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<CorpDevPage />)
    expect(await screen.findByText(/no disclosure approvals/i)).toBeInTheDocument()
  })
})
