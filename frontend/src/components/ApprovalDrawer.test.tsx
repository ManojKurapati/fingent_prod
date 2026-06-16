import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApprovalDrawer } from './ApprovalDrawer'
import { sampleApproval } from '../test/server'

describe('ApprovalDrawer', () => {
  it('renders nothing when there is no approval', () => {
    const { container } = render(
      <ApprovalDrawer approval={null} onApprove={vi.fn()} onReject={vi.fn()} onClose={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the proposed action, rationale and required approver', () => {
    render(
      <ApprovalDrawer
        approval={sampleApproval}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('template_publish')).toBeInTheDocument()
    expect(screen.getByText(/end-of-day sweep/)).toBeInTheDocument()
    expect(screen.getByText(/treasurer/)).toBeInTheDocument()
  })

  it('calls onApprove with the entered approver', async () => {
    const onApprove = vi.fn()
    render(
      <ApprovalDrawer
        approval={sampleApproval}
        onApprove={onApprove}
        onReject={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'alice')
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledWith('alice')
  })

  it('requires an approver before approving (gate stays closed)', async () => {
    const onApprove = vi.fn()
    render(
      <ApprovalDrawer
        approval={sampleApproval}
        onApprove={onApprove}
        onReject={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    // no approver typed -> approve button disabled
    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(onApprove).not.toHaveBeenCalled()
  })

  it('calls onReject with approver and reason', async () => {
    const onReject = vi.fn()
    render(
      <ApprovalDrawer
        approval={sampleApproval}
        onApprove={vi.fn()}
        onReject={onReject}
        onClose={vi.fn()}
      />,
    )
    await userEvent.type(screen.getByLabelText(/approver/i), 'bob')
    await userEvent.type(screen.getByLabelText(/reason/i), 'over limit')
    await userEvent.click(screen.getByRole('button', { name: /reject/i }))
    expect(onReject).toHaveBeenCalledWith('bob', 'over limit')
  })

  it('calls onClose', async () => {
    const onClose = vi.fn()
    render(
      <ApprovalDrawer
        approval={sampleApproval}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onClose={onClose}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
