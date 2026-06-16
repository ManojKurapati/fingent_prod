import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { startProcess, startRecon } from './api'

describe('operations api', () => {
  it('posts a process request', async () => {
    server.use(http.post('/agents/ops/process', () => HttpResponse.json({ job_id: 'job-p' })))
    expect(await startProcess({ trade_id: 'T1', amount: 1000 })).toEqual({ job_id: 'job-p' })
  })

  it('posts a recon request', async () => {
    server.use(http.post('/agents/ops/recon', () => HttpResponse.json({ job_id: 'job-r' })))
    expect(await startRecon({ as_of: '2026-06-16' })).toEqual({ job_id: 'job-r' })
  })

  it('throws on a non-ok response', async () => {
    server.use(http.post('/agents/ops/recon', () => new HttpResponse(null, { status: 500 })))
    await expect(startRecon({ as_of: '2026-06-16' })).rejects.toThrow(/failed: 500/)
  })
})
