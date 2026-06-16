import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { TaxPage } from './TaxPage'

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
    const data = JSON.stringify({ job_id: 'job-tax', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const filingApproval: Approval = {
  id: 'req-file-us',
  tool_name: 'tax_file_return',
  actor: 'tax',
  approver_role: 'head-of-tax',
  rationale: 'file return ret-US-2026 in US',
  state: 'pending',
  decided_by: null,
}

describe('TaxPage', () => {
  it('renders the workbench heading and regions', () => {
    render(<TaxPage />)
    expect(screen.getByRole('heading', { name: /tax workbench/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /provision and etr/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /filing tracker/i })).toBeInTheDocument()
  })

  it('runs a provision, greens the streams, and shows the ETR', async () => {
    server.use(
      http.post('/agents/tax/provision', () => HttpResponse.json({ job_id: 'job-tax' })),
      http.get('/jobs/:id', () =>
        HttpResponse.json({
          id: 'job-tax',
          kind: 'tax.provision',
          status: 'completed',
          attempts: 1,
          error: null,
          result: {
            'tax-provision': { current: 335, deferred: 70, total_tax: 405, etr: 0.27 },
          },
        }),
      ),
    )

    render(<TaxPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /run provision/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-tax/events')

    const grid = screen.getByRole('region', { name: /provision and etr/i })
    act(() => es.emit('direct-tax-compliance', 'completed'))
    expect(await within(grid).findByTestId('step-direct-tax-compliance')).toHaveAttribute(
      'data-status',
      'completed',
    )

    act(() => es.emit('tax-provision', 'completed'))
    expect(await within(grid).findByText(/27\.0%/)).toBeInTheDocument()
  })

  it('files a return', async () => {
    let filed = false
    server.use(
      http.post('/agents/tax/file/:returnId', () => {
        filed = true
        return HttpResponse.json({ job_id: 'job-file' })
      }),
    )
    render(<TaxPage />)
    await userEvent.click(screen.getByRole('button', { name: /file return/i }))
    await waitFor(() => expect(filed).toBe(true))
  })

  it('lists a filing approval and approves it (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [filingApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...filingApproval, state: 'approved', decided_by: 'jo' },
        })
      }),
    )

    render(<TaxPage />)
    await userEvent.click(await screen.findByRole('button', { name: /tax_file_return/i }))

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'jo')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no filing approvals/i)).toBeInTheDocument())
  })

  it('rejects a filing approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([filingApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...filingApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<TaxPage />)
    await userEvent.click(await screen.findByRole('button', { name: /tax_file_return/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'recheck figures')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<TaxPage />)
    expect(await screen.findByText(/no filing approvals/i)).toBeInTheDocument()
  })
})
