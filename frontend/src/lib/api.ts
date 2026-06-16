// REST API client for the shared platform — FROZEN CONTRACT.

import { authHeaders } from './auth'
import type { Approval, DecisionResult, Job } from './types'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init.headers ?? {}),
    },
  })
  if (!res.ok) {
    throw new Error(`request to ${path} failed: ${res.status}`)
  }
  return (await res.json()) as T
}

export function listApprovals(): Promise<Approval[]> {
  return request<Approval[]>('/approvals')
}

export function approveRequest(id: string, approver: string): Promise<DecisionResult> {
  return request<DecisionResult>(`/approvals/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approver }),
  })
}

export function rejectRequest(id: string, approver: string, reason: string): Promise<DecisionResult> {
  return request<DecisionResult>(`/approvals/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ approver, reason }),
  })
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}`)
}
