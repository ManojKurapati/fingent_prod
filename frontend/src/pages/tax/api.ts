// Tax API calls. The shared platform client (lib/api) is frozen, so the agent's
// own endpoints live here. Job status/SSE reuse the shared client.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface ProvisionInput {
  period: string
  jurisdictions: string[]
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

export function startProvision(input: ProvisionInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/tax/provision', input)
}

export function fileReturn(returnId: string, jurisdiction: string): Promise<RunAccepted> {
  return post<RunAccepted>(`/agents/tax/file/${encodeURIComponent(returnId)}`, { jurisdiction })
}
