// Shared types mirroring the backend platform contracts.

export type ApprovalState = 'pending' | 'approved' | 'rejected'

export interface Approval {
  id: string
  tool_name: string
  actor: string
  approver_role: string
  rationale: string
  state: ApprovalState
  decided_by: string | null
}

export interface DecisionResult {
  executed: boolean
  request: Approval
}

export type JobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  attempts: number
  result: unknown | null
  error: string | null
}

export interface JobEvent {
  job_id: string
  type: string
  payload: Record<string, unknown>
}
