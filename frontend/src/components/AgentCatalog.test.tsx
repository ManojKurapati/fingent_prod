import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentCatalog } from './AgentCatalog'

beforeEach(() => globalThis.localStorage.clear())

describe('AgentCatalog', () => {
  it('renders organisation sections and group tiles', () => {
    render(<AgentCatalog onOpen={() => {}} />)
    expect(screen.getByRole('region', { name: /enterprise finance/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /financial services/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /fp&a planning/i })).toBeInTheDocument()
  })

  it('deploys a group through the deploy modal asking for portal keys', async () => {
    render(<AgentCatalog onOpen={() => {}} />)

    await userEvent.click(screen.getAllByRole('button', { name: 'Deploy' })[0])

    const dialog = screen.getByRole('dialog')
    // fill every portal credential field + the approver the modal asks for
    for (const input of dialog.querySelectorAll('input')) {
      await userEvent.type(input, 'value')
    }

    const deployBtn = within(dialog).getByRole('button', { name: /deploy group/i })
    await userEvent.click(deployBtn)

    // modal closed, tile now shows it is live
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getAllByText(/● live/i).length).toBeGreaterThan(0)
  })

  it('opens a deployed group dashboard', async () => {
    const onOpen = vi.fn()
    render(<AgentCatalog onOpen={onOpen} />)
    // "Preview" opens the dashboard for an undeployed group with a page
    await userEvent.click(screen.getAllByRole('button', { name: /preview/i })[0])
    expect(onOpen).toHaveBeenCalled()
  })
})
