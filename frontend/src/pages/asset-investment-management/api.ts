// Asset & Investment Management API calls. The shared platform client (lib/api)
// is frozen, so the agent's own endpoints live here.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface RebalanceInput {
  portfolio_id: string
  names: string[]
  period?: string
}

export interface ResearchInput {
  names: string[]
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

export function startRebalance(input: RebalanceInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/asset-investment-management/rebalance', input)
}

export function startResearch(input: ResearchInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/asset-investment-management/research', input)
}
