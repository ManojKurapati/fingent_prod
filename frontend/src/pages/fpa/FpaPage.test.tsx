import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { FpaPage } from './FpaPage'

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
    const data = JSON.stringify({ job_id: 'job-fpa', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const fpaApproval: Approval = {
  id: 'req-cc1',
  tool_name: 'fpa_request_commentary',
  actor: 'fpa',
  approver_role: 'fpa-manager',
  rationale: 'variance 20% on cc1 exceeds 10%',
  state: 'pending',
  decided_by: null,
}

describe('FpaPage', () => {
  it('renders the planning dashboard heading and regions', () => {
    render(<FpaPage />)
    expect(screen.getByRole('heading', { name: /fp&a planning/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /variance/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /scenario sandbox/i })).toBeInTheDocument()
  })

  it('runs a forecast and turns the variance grid green as workers finish', async () => {
    server.use(http.post('/agents/fpa/forecast', () => HttpResponse.json({ job_id: 'job-fpa' })))

    render(<FpaPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run forecast/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-fpa/events')

    act(() => es.emit('variance:cc1', 'running'))
    const grid = screen.getByRole('region', { name: /variance/i })
    expect(await within(grid).findByTestId('step-variance:cc1')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('variance:cc1', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-variance:cc1')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists the variance-commentary approval and approves it (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [fpaApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...fpaApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<FpaPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /fpa_request_commentary/i }),
    )

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no commentary requests/i)).toBeInTheDocument())
  })

  it('rejects a variance-commentary approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([fpaApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...fpaApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<FpaPage />)
    await userEvent.click(await screen.findByRole('button', { name: /fpa_request_commentary/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'need detail')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('runs a scenario and shows base vs adjusted', async () => {
    server.use(
      http.post('/agents/fpa/scenario', () => HttpResponse.json({ job_id: 'job-scn' })),
      http.get('/jobs/:id', () =>
        HttpResponse.json({
          id: 'job-scn',
          kind: 'fpa.scenario',
          status: 'completed',
          attempts: 1,
          error: null,
          result: { 'scenario-modelling': { base: 222, adjusted: 244.2, drivers: { price: 0.1 } } },
        }),
      ),
    )

    render(<FpaPage />)
    const sandbox = screen.getByRole('region', { name: /scenario sandbox/i })
    await userEvent.clear(within(sandbox).getByLabelText(/driver/i))
    await userEvent.type(within(sandbox).getByLabelText(/driver/i), '0.1')
    await userEvent.click(within(sandbox).getByRole('button', { name: /run scenario/i }))

    expect(await within(sandbox).findByText(/244.2/)).toBeInTheDocument()
    expect(within(sandbox).getByText(/222/)).toBeInTheDocument()
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<FpaPage />)
    expect(await screen.findByText(/no commentary requests/i)).toBeInTheDocument()
  })
})
