import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { JobTimeline } from './JobTimeline'
import type { JobEvent } from '../lib/types'

const events: JobEvent[] = [
  { job_id: 'j', type: 'step', payload: { step: 'data-intake', status: 'completed' } },
  { job_id: 'j', type: 'step', payload: { step: 'analyze:cc1', status: 'running' } },
  { job_id: 'j', type: 'status', payload: { state: 'running' } },
]

describe('JobTimeline', () => {
  it('renders an empty state when there are no events', () => {
    render(<JobTimeline events={[]} />)
    expect(screen.getByText(/no activity/i)).toBeInTheDocument()
  })

  it('renders one row per step with its status', () => {
    render(<JobTimeline events={events} />)
    expect(screen.getByText('data-intake')).toBeInTheDocument()
    expect(screen.getByText('analyze:cc1')).toBeInTheDocument()
  })

  it('marks completed steps so the grid can turn green', () => {
    render(<JobTimeline events={events} />)
    const completed = screen.getByTestId('step-data-intake')
    expect(completed).toHaveAttribute('data-status', 'completed')
  })
})
