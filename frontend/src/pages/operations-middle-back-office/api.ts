// Operations-specific API calls. The shared platform client (lib/api) is frozen,
// so the agent's own endpoints live here. Job status/SSE reuse the shared client.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface ProcessInput {
  trade_id: string
  amount: number
}

export interface ReconInput {
  as_of: string
}

export interface RunAccepted {
  job_id: string
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`request to ${path} failed: ${res.status}`)
  return (await res.json()) as T
}

export function startProcess(input: ProcessInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/ops/process', input)
}

export function startRecon(input: ReconInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/ops/recon', input)
}
