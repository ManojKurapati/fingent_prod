// Treasury API calls. The shared platform client (lib/api) is frozen, so the
// agent's own endpoints live here. Job status/SSE reuse the shared client.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface DailyPositionInput {
  as_of: string
  accounts: string[]
}

export interface HedgeExecuteInput {
  pair: string
  notional: number
}

export interface SweepInput {
  from_account: string
  to_account: string
  amount: number
}

export interface RunAccepted {
  job_id: string
}

export interface GateAccepted {
  executed: boolean
  approval_id: string | null
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

export function startDailyPosition(input: DailyPositionInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/treasury/daily-position', input)
}

export function executeHedge(input: HedgeExecuteInput): Promise<GateAccepted> {
  return post<GateAccepted>('/agents/treasury/hedge/execute', input)
}

export function executeSweep(input: SweepInput): Promise<GateAccepted> {
  return post<GateAccepted>('/agents/treasury/sweep', input)
}
