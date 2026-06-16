import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { approveRequest, getJob, listApprovals, rejectRequest } from './api'
import { login, logout } from './auth'
import { server } from '../test/server'

describe('api client', () => {
  afterEach(() => logout())

  it('lists pending approvals', async () => {
    const approvals = await listApprovals()
    expect(approvals).toHaveLength(1)
    expect(approvals[0].tool_name).toBe('template_publish')
  })

  it('approves a request', async () => {
    const result = await approveRequest('req-1', 'alice')
    expect(result.executed).toBe(true)
    expect(result.request.state).toBe('approved')
    expect(result.request.decided_by).toBe('alice')
  })

  it('rejects a request', async () => {
    const result = await rejectRequest('req-1', 'bob', 'over limit')
    expect(result.executed).toBe(false)
    expect(result.request.state).toBe('rejected')
  })

  it('fetches a job', async () => {
    const job = await getJob('job-9')
    expect(job.id).toBe('job-9')
    expect(job.status).toBe('completed')
  })

  it('sends the auth bearer header when logged in', async () => {
    let seen: string | null = null
    server.use(
      http.get('/approvals', ({ request }) => {
        seen = request.headers.get('authorization')
        return HttpResponse.json([])
      }),
    )
    login('secret')
    await listApprovals()
    expect(seen).toBe('Bearer secret')
  })

  it('throws on a non-ok response', async () => {
    server.use(http.get('/jobs/:id', () => new HttpResponse(null, { status: 404 })))
    await expect(getJob('missing')).rejects.toThrow(/404/)
  })
})
