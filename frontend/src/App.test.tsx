import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { App } from './App'
import { sampleApproval, server } from './test/server'

describe('App shell', () => {
  it('renders the platform heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /finance platform/i })).toBeInTheDocument()
  })

  it('shows the approvals queue region', () => {
    render(<App />)
    expect(screen.getByRole('region', { name: /approvals/i })).toBeInTheDocument()
  })

  it('lists pending approvals fetched from the API', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: /template_publish/i })).toBeInTheDocument()
  })

  it('opens the drawer and approves a selected request', async () => {
    let approved = false
    server.use(
      http.post('/approvals/:id/approve', () => {
        approved = true
        return HttpResponse.json({
          executed: true,
          request: { ...sampleApproval, state: 'approved', decided_by: 'alice' },
        })
      }),
      // after approval the queue is empty
      http.get('/approvals', () =>
        HttpResponse.json(approved ? [] : [sampleApproval]),
      ),
    )

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /template_publish/i }))

    // drawer opens
    expect(screen.getByRole('dialog', { name: /approval/i })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/approver/i), 'alice')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    expect(approved).toBe(true)
    await waitFor(() => expect(screen.getByText(/no pending approvals/i)).toBeInTheDocument())
  })

  it('rejects a selected request', async () => {
    let rejected = false
    server.use(
      http.post('/approvals/:id/reject', () => {
        rejected = true
        return HttpResponse.json({
          executed: false,
          request: { ...sampleApproval, state: 'rejected', decided_by: 'bob' },
        })
      }),
    )

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /template_publish/i }))
    await userEvent.type(screen.getByLabelText(/approver/i), 'bob')
    await userEvent.type(screen.getByLabelText(/reason/i), 'over limit')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    await waitFor(() => expect(rejected).toBe(true))
  })

  it('handles an approvals fetch failure gracefully', async () => {
    server.use(http.get('/approvals', () => new HttpResponse(null, { status: 500 })))
    render(<App />)
    expect(await screen.findByText(/no pending approvals/i)).toBeInTheDocument()
  })
})
