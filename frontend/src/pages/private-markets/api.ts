// Private Markets-specific API calls. The shared platform client (lib/api) is
// frozen, so the agent's own endpoints live here. Job status/SSE reuse lib/.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface DealInput {
  deal_id: string
  asset_class: 'pe_vc' | 'credit' | 'real_asset' | 'fund_of_funds'
  sponsor: string
}

export interface MonitorInput {
  portfolio_id: string
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

export function startDeal(input: DealInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/private-markets/deals', input)
}

export function startMonitor(input: MonitorInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/private-markets/monitor', input)
}
