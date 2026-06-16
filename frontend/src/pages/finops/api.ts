// Finance Systems & Operations-specific API calls. The shared platform client
// (lib/api) is frozen, so the agent's own endpoints live here. Job status/SSE
// reuse the shared client.

import { authHeaders } from '../../lib/auth'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface OperationsInput {
  period: string
  sources: string[]
  access_changes?: string[]
}

export interface AccessChangeInput {
  change: string
  role: string
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

export function startPipelineRun(input: OperationsInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/finops/pipeline/run', input)
}

export function startAccessChange(input: AccessChangeInput): Promise<RunAccepted> {
  return post<RunAccepted>('/agents/finops/erp/access-change', input)
}
