// One-click deploy flow for an agent group. Asks for the API keys of any portal
// the group needs that isn't already connected, plus the human approver role,
// then records the deployment.

import { useMemo, useState } from 'react'
import { PORTALS_BY_ID, humanizeAgent, type AgentGroup } from '../lib/catalog'
import { usePlatformStore } from '../lib/deployments'
import { Modal } from './Modal'

export interface DeployModalProps {
  group: AgentGroup
  onClose: () => void
  onDeployed?: (group: AgentGroup) => void
}

export function DeployModal({ group, onClose, onDeployed }: DeployModalProps) {
  const { connections, connectPortal, deployGroup } = usePlatformStore()
  const [approver, setApprover] = useState('')
  // values entered per portal field, keyed `${portalId}.${fieldKey}`
  const [values, setValues] = useState<Record<string, string>>({})

  const portals = useMemo(() => group.portals.map((id) => PORTALS_BY_ID[id]).filter(Boolean), [group])
  const unconnected = portals.filter((p) => !connections[p.id])

  const missingKeys = unconnected.some((p) =>
    p.fields.some((f) => !(values[`${p.id}.${f.key}`] ?? '').trim()),
  )
  const canDeploy = approver.trim().length > 0 && !missingKeys

  const set = (portalId: string, fieldKey: string, v: string) =>
    setValues((prev) => ({ ...prev, [`${portalId}.${fieldKey}`]: v }))

  const deploy = () => {
    // Persist any newly-supplied portal credentials, then record the deployment.
    for (const p of unconnected) {
      const vals: Record<string, string> = {}
      for (const f of p.fields) vals[f.key] = (values[`${p.id}.${f.key}`] ?? '').trim()
      connectPortal(p.id, vals)
    }
    deployGroup(group.id, approver.trim(), group.portals)
    onDeployed?.(group)
    onClose()
  }

  return (
    <Modal
      title={`Deploy ${group.title}`}
      subtitle={`${group.agents.length} agents · approver-gated · ${group.portals.length} portals`}
      onClose={onClose}
    >
      <div className="deploy-section">
        <h3>Agents in this group</h3>
        <div className="chip-row">
          {group.agents.map((a) => (
            <span key={a} className="chip">
              {humanizeAgent(a)}
            </span>
          ))}
        </div>
      </div>

      <div className="deploy-section">
        <h3>Connect required portals</h3>
        <div className="portal-config">
          {portals.map((p) => {
            const connected = Boolean(connections[p.id])
            return (
              <div key={p.id} className="portal-config-row">
                <div className="portal-config-head">
                  <span className="portal-ico" aria-hidden="true">
                    {p.icon}
                  </span>
                  <div>
                    <strong>{p.name}</strong>
                    <span className="muted"> · {p.category}</span>
                  </div>
                  {connected ? (
                    <span className="tag tag-ok">Connected</span>
                  ) : (
                    <span className="tag tag-warn">Needs key</span>
                  )}
                </div>
                {!connected &&
                  p.fields.map((f) => (
                    <label key={f.key}>
                      {f.label}
                      <input
                        type={f.secret ? 'password' : 'text'}
                        placeholder={f.placeholder}
                        value={values[`${p.id}.${f.key}`] ?? ''}
                        onChange={(e) => set(p.id, f.key, e.target.value)}
                      />
                    </label>
                  ))}
              </div>
            )
          })}
        </div>
      </div>

      <div className="deploy-section">
        <h3>Human-in-the-loop approver</h3>
        <label>
          Approver role / email
          <input
            value={approver}
            placeholder="e.g. cfo@firm.com"
            onChange={(e) => setApprover(e.target.value)}
          />
        </label>
        <p className="muted">
          Every consequential action this group proposes pauses for this approver.
        </p>
      </div>

      <div className="modal-actions">
        <button type="button" className="btn ghost" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="btn" disabled={!canDeploy} onClick={deploy}>
          Deploy group
        </button>
      </div>
    </Modal>
  )
}
