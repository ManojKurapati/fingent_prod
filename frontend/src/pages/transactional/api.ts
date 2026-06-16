// Transactional / Operational Finance API calls. The shared platform client
// (lib/api) is frozen, so the agent's own endpoints live here. Job status/SSE
// reuse the shared client.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface CycleInput {
  period: string
  vendors: string[]
  customers: string[]
  employees?: string[]
}

export interface PaymentRunInput {
  period: string
  vendors: string[]
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

export function startCycle(input: CycleInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/transactional/cycle/run', input)
}

export function startPaymentRun(input: PaymentRunInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/transactional/ap/run', input)
}
