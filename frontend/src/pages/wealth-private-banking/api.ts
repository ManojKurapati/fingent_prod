// Wealth & Private Banking-specific API calls. The shared platform client
// (lib/api) is frozen, so the agent's own endpoints live here.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface OnboardInput {
  client_id: string
  segment: 'hnw' | 'uhnw'
  name: string
}

export interface RebalanceInput {
  client_id: string
  proposed_risk: number
}

export interface CreditInput {
  client_id: string
  loan_amount: number
  facility: 'lombard' | 'mortgage'
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

export function startOnboarding(input: OnboardInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/wealth-private-banking/clients', input)
}

export function startRebalance(input: RebalanceInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/wealth-private-banking/rebalance', input)
}

export function startCredit(input: CreditInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/wealth-private-banking/credit', input)
}
