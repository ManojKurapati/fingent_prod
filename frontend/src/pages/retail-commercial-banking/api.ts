// Retail & Commercial Banking-specific API calls. The shared platform client
// (lib/api) is frozen, so the agent's own endpoints live here.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface ApplicationInput {
  application_id: string
  channel: 'personal' | 'commercial' | 'branch'
  applicant: string
  loan_amount: number
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

export function startApplication(input: ApplicationInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/retail-commercial-banking/applications', input)
}
