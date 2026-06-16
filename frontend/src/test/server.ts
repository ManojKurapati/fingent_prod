import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { Approval, Job } from '../lib/types'

export const sampleApproval: Approval = {
  id: 'req-1',
  tool_name: 'template_publish',
  actor: 'treasury',
  approver_role: 'treasurer',
  rationale: 'end-of-day sweep',
  state: 'pending',
  decided_by: null,
}

export const sampleJob: Job = {
  id: 'job-1',
  kind: 'template.run',
  status: 'completed',
  attempts: 1,
  result: { 'reporting-pack': { sections: 2 } },
  error: null,
}

export const handlers = [
  http.get('/approvals', () => HttpResponse.json([sampleApproval])),
  http.post('/approvals/:id/approve', async ({ params }) =>
    HttpResponse.json({
      executed: true,
      request: { ...sampleApproval, id: String(params.id), state: 'approved', decided_by: 'alice' },
    }),
  ),
  http.post('/approvals/:id/reject', async ({ params }) =>
    HttpResponse.json({
      executed: false,
      request: { ...sampleApproval, id: String(params.id), state: 'rejected', decided_by: 'bob' },
    }),
  ),
  http.get('/jobs/:id', ({ params }) =>
    HttpResponse.json({ ...sampleJob, id: String(params.id) }),
  ),
]

export const server = setupServer(...handlers)
