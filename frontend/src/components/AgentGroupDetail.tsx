// Friendly "what can this agent do & how do I use it" panel. Opens when a user
// clicks an agent group in the catalog: plain-English capabilities, the team of
// subagents (gates flagged), the portals it plugs into, and a 3-step how-to —
// then the deploy / open actions right there.

import { ORGANISATIONS, PORTALS_BY_ID, humanizeAgent, isGateAgent, type AgentGroup } from '../lib/catalog'
import { Modal } from './Modal'

export interface AgentGroupDetailProps {
  group: AgentGroup
  deployed: boolean
  connections: Record<string, unknown>
  onDeploy: (group: AgentGroup) => void
  onOpen: (page: string) => void
  onUndeploy: (id: string) => void
  onClose: () => void
}

export function AgentGroupDetail({
  group,
  deployed,
  connections,
  onDeploy,
  onOpen,
  onUndeploy,
  onClose,
}: AgentGroupDetailProps) {
  const org = ORGANISATIONS.find((o) => o.id === group.org)

  return (
    <Modal
      title={`${group.icon}  ${group.title}`}
      subtitle={`${org?.name ?? ''} · ${group.agents.length} agents · ${group.portals.length} portals${deployed ? ' · ● Live' : ''}`}
      onClose={onClose}
    >
      <section className="detail-section">
        <h3>What you can do here</h3>
        <ul className="cap-list">
          {group.capabilities.map((c) => (
            <li key={c}>
              <span className="cap-tick" aria-hidden="true">
                ✓
              </span>
              {c}
            </li>
          ))}
        </ul>
      </section>

      <section className="detail-section">
        <h3>Who does the work</h3>
        <p className="detail-lead">
          One orchestrator coordinates these specialist subagents. Steps marked{' '}
          <span className="gate-badge sm">⛔ Gate</span> always pause for a human before anything happens.
        </p>
        <div className="agent-list">
          {group.agents.map((a) => (
            <div key={a} className={`agent-row ${isGateAgent(a) ? 'is-gate' : ''}`}>
              <span className="agent-name">{humanizeAgent(a)}</span>
              {isGateAgent(a) && <span className="gate-badge">⛔ Approval gate</span>}
            </div>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>Connects to</h3>
        <div className="tile-portals">
          {group.portals.map((pid) => {
            const portal = PORTALS_BY_ID[pid]
            const on = Boolean(connections[pid])
            return (
              <span key={pid} className={`portal-pill ${on ? 'on' : ''}`}>
                <span aria-hidden="true">{portal?.icon}</span> {portal?.name}
                {on && ' ✓'}
              </span>
            )
          })}
        </div>
      </section>

      <section className="detail-section">
        <h3>How to use it</h3>
        <ol className="howto">
          <li>
            <strong>Deploy &amp; connect.</strong> Click deploy, add keys for the portals above, and name the
            human approver.
          </li>
          <li>
            <strong>Run a task.</strong> Open the dashboard and kick off a job — the orchestrator fans work
            out to the subagents and streams progress live.
          </li>
          <li>
            <strong>Approve &amp; ship.</strong> Anything consequential lands in your approvals queue. Nothing
            posts, pays, trades, or files until you say so.
          </li>
        </ol>
      </section>

      <div className="modal-actions">
        {deployed ? (
          <>
            <button type="button" className="btn ghost" onClick={() => onUndeploy(group.id)}>
              Undeploy
            </button>
            {group.page && (
              <button type="button" className="btn" onClick={() => onOpen(group.page as string)}>
                Open dashboard →
              </button>
            )}
          </>
        ) : (
          <>
            {group.page && (
              <button type="button" className="btn ghost" onClick={() => onOpen(group.page as string)}>
                Preview dashboard
              </button>
            )}
            <button type="button" className="btn" onClick={() => onDeploy(group)}>
              Deploy this group
            </button>
          </>
        )}
      </div>
    </Modal>
  )
}
