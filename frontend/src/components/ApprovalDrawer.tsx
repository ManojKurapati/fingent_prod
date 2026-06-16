// Reusable human-in-the-loop approval gate — FROZEN CONTRACT (props shape).
//
// Renders a consequential action proposed by an agent and blocks until a human
// approves or rejects. Approve is disabled until an approver is named, so the
// gate cannot be cleared by accident.

import { useState } from 'react'
import type { Approval } from '../lib/types'

export interface ApprovalDrawerProps {
  approval: Approval | null
  onApprove: (approver: string) => void
  onReject: (approver: string, reason: string) => void
  onClose: () => void
}

export function ApprovalDrawer({ approval, onApprove, onReject, onClose }: ApprovalDrawerProps) {
  const [approver, setApprover] = useState('')
  const [reason, setReason] = useState('')

  if (!approval) return null

  const canApprove = approver.trim().length > 0

  return (
    <aside role="dialog" aria-label="Approval request" className="approval-drawer">
      <header>
        <h2>Approval required</h2>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>

      <dl>
        <dt>Proposed action</dt>
        <dd>{approval.tool_name}</dd>
        <dt>Proposed by</dt>
        <dd>{approval.actor}</dd>
        <dt>Required approver</dt>
        <dd>{approval.approver_role}</dd>
        <dt>Rationale</dt>
        <dd>{approval.rationale}</dd>
      </dl>

      <label>
        Approver
        <input value={approver} onChange={(e) => setApprover(e.target.value)} />
      </label>
      <label>
        Reason (for rejection)
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>

      <footer>
        <button type="button" disabled={!canApprove} onClick={() => onApprove(approver.trim())}>
          Approve
        </button>
        <button type="button" disabled={!canApprove} onClick={() => onReject(approver.trim(), reason.trim())}>
          Reject
        </button>
      </footer>
    </aside>
  )
}
