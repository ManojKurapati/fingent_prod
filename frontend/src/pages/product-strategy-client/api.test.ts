import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { startCommercial, startInitiative } from './api'

describe('product api', () => {
  it('posts an initiative request', async () => {
    server.use(
      http.post('/agents/product/initiatives', () => HttpResponse.json({ job_id: 'job-i' })),
    )
    expect(await startInitiative({ name: 'FX-Hedge', filing_token: 'FT-1' })).toEqual({
      job_id: 'job-i',
    })
  })

  it('posts a commercial request', async () => {
    server.use(
      http.post('/agents/product/commercial', () => HttpResponse.json({ job_id: 'job-c' })),
    )
    expect(await startCommercial({ client_id: 'C1', kyc_token: 'KT-1' })).toEqual({
      job_id: 'job-c',
    })
  })

  it('throws on a non-ok response', async () => {
    server.use(http.post('/agents/product/commercial', () => new HttpResponse(null, { status: 500 })))
    await expect(startCommercial({ client_id: 'C1' })).rejects.toThrow(/failed: 500/)
  })
})
