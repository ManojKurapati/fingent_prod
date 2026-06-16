import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { Approval } from '../../lib/types'
import { server } from '../../test/server'
import { AccountingPage } from './AccountingPage'

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
    const data = JSON.stringify({ job_id: 'job-acc', type: 'step', payload: { step, status } })
    for (const cb of this.listeners['step'] ?? []) cb({ data } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const ledgerApproval: Approval = {
  id: 'req-je',
  tool_name: 'accounting_post_journal_entry',
  actor: 'accounting',
  approver_role: 'controller',
  rationale: 'post period-close journal entries totalling 500',
  state: 'pending',
  decided_by: null,
}

describe('AccountingPage', () => {
  it('renders the close cockpit heading and regions', () => {
    render(<AccountingPage />)
    expect(screen.getByRole('heading', { name: /accounting close/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /close checklist/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /ledger post approvals/i })).toBeInTheDocument()
  })

  it('starts a close and greens the checklist as sub-ledgers finish', async () => {
    server.use(
      http.post('/agents/accounting/close/start', () => HttpResponse.json({ job_id: 'job-acc' })),
      http.get('/approvals', () => HttpResponse.json([])),
    )

    render(<AccountingPage eventSource={FakeEventSource as never} />)
    await userEvent.click(screen.getByRole('button', { name: /start close/i }))

    const es = await waitFor(() => {
      const inst = FakeEventSource.instances.at(-1)
      if (!inst) throw new Error('no subscription yet')
      return inst
    })
    expect(es.url).toContain('/jobs/job-acc/events')

    act(() => es.emit('journal-entries', 'running'))
    const grid = screen.getByRole('region', { name: /close checklist/i })
    expect(await within(grid).findByTestId('step-journal-entries')).toHaveAttribute(
      'data-status',
      'running',
    )

    act(() => es.emit('journal-entries', 'completed'))
    await waitFor(() =>
      expect(within(grid).getByTestId('step-journal-entries')).toHaveAttribute(
        'data-status',
        'completed',
      ),
    )
  })

  it('lists the GL ledger-post approval and approves it (human-in-the-loop)', async () => {
    let approved = false
    server.use(
      http.get('/approvals', () => HttpResponse.json(approved ? [] : [ledgerApproval])),
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...ledgerApproval, state: 'approved', decided_by: 'sam' },
        })
      }),
    )

    render(<AccountingPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /accounting_post_journal_entry/i }),
    )

    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'sam')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/no ledger posts awaiting approval/i)).toBeInTheDocument(),
    )
  })

  it('rejects a ledger-post approval', async () => {
    let rejected = false
    server.use(
      http.get('/approvals', () => HttpResponse.json([ledgerApproval])),
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...ledgerApproval, state: 'rejected', decided_by: 'bo' },
        })
      }),
    )

    render(<AccountingPage />)
    await userEvent.click(
      await screen.findByRole('button', { name: /accounting_post_journal_entry/i }),
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'bo')
    await userEvent.type(screen.getByLabelText(/reason/i), 'need backup')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<AccountingPage />)
    expect(await screen.findByText(/no ledger posts awaiting approval/i)).toBeInTheDocument()
  })
})
