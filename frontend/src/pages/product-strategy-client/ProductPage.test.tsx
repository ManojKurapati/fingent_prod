import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { ProductPage } from './ProductPage'

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
    const data = JSON.stringify({ job_id: 'job-pr', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const launchApproval: Approval = {
  id: 'req-l1',
  tool_name: 'product_launch',
  actor: 'product',
  approver_role: 'cpo',
  rationale: 'launch product FX-Hedge',
  state: 'pending',
  decided_by: null,
}

describe('ProductPage', () => {
  it('renders the initiative and launch-approval regions', () => {
    render(<ProductPage />)
    expect(
      screen.getByRole('heading', { name: /product, strategy & client/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /product initiative/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /launch approvals/i })).toBeInTheDocument()
  })

  it('runs an initiative and greens the launch step as it finishes', async () => {
    let body: unknown = null
    server.use(
      http.post('/agents/product/initiatives', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ job_id: 'job-pr' })
      }),
    )

    render(<ProductPage eventSource={FakeEventSource as never} />)
    const region = screen.getByRole('region', { name: /product initiative/i })
    await userEvent.type(within(region).getByLabelText(/filing token/i), 'FT-1')
    await userEvent.click(within(region).getByRole('button', { name: /run initiative/i }))

    await waitFor(() => expect(body).toEqual({ name: 'FX-Hedge', filing_token: 'FT-1' }))

    const es = FakeEventSource.instances.at(-1)!
    expect(es.url).toContain('/jobs/job-pr/events')
    act(() => es.emit('launch', 'completed'))
    await waitFor(() =>
      expect(within(region).getByTestId('step-launch')).toHaveAttribute('data-status', 'completed'),
    )
  })

  it('lists a launch approval and approves it (launch-approval gate)', async () => {
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

    render(<ProductPage />)
    await userEvent.click(await screen.findByRole('button', { name: /product_launch/i }))
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no launches awaiting approval/i)).toBeInTheDocument())
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

    render(<ProductPage />)
    await userEvent.click(await screen.findByRole('button', { name: /product_launch/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'filing incomplete')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<ProductPage />)
    expect(await screen.findByText(/no launches awaiting approval/i)).toBeInTheDocument()
  })
})
