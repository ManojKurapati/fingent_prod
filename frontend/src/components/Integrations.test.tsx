import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { Integrations } from './Integrations'

beforeEach(() => globalThis.localStorage.clear())

describe('Integrations', () => {
  it('renders portal categories', () => {
    render(<Integrations />)
    expect(screen.getByRole('region', { name: /model provider/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /market data/i })).toBeInTheDocument()
  })

  it('connects a portal through the modal and reflects connected state', async () => {
    render(<Integrations />)

    await userEvent.click(screen.getAllByRole('button', { name: 'Connect' })[0])
    const dialog = screen.getByRole('dialog')

    for (const input of dialog.querySelectorAll('input')) {
      await userEvent.type(input, 'value')
    }

    await userEvent.click(within(dialog).getByRole('button', { name: /save connection/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getAllByText(/● connected/i).length).toBeGreaterThan(0)
  })

  it('closes the modal on cancel', async () => {
    render(<Integrations />)
    await userEvent.click(screen.getAllByRole('button', { name: 'Connect' })[0])
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
