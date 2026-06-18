// Per-dashboard context panel. Renders at the top of every group dashboard so a
// human always knows what the agent group does, who does the work (subagents,
// with approval gates flagged), what it connects to, and how to drive the panels
// below. Pure presentation, data-driven from the catalog — keyed by the group's
// `page` id so App can drop it above any page with one line.

import {
  GROUPS,
  ORGANISATIONS,
  PORTALS_BY_ID,
  humanizeAgent,
  isGateAgent,
  type AgentGroup,
} from '../lib/catalog'

export interface GroupIntroProps {
  /** Dashboard view id — matches AgentGroup.page in catalog.ts. */
  page: string
}

const GROUP_BY_PAGE: Record<string, AgentGroup> = Object.fromEntries(
  GROUPS.filter((g) => g.page).map((g) => [g.page as string, g]),
)

export function GroupIntro({ page }: GroupIntroProps) {
  const group = GROUP_BY_PAGE[page]
  if (!group) return null

  const org = ORGANISATIONS.find((o) => o.id === group.org)
  const gateCount = group.agents.filter(isGateAgent).length

  return (
    <section className="group-intro" aria-label="About this agent group">
      <div className="gi-head">
        <span className="gi-ico" aria-hidden="true">
          {group.icon}
        </span>
        <div className="gi-headings">
          <p className="gi-blurb">{group.blurb}</p>
          <p className="gi-meta">
            {org?.name} · {group.agents.length} subagents · {group.portals.length} portals
            {gateCount > 0 && ` · ${gateCount} approval gate${gateCount > 1 ? 's' : ''}`}
          </p>
        </div>
      </div>

      <details className="gi-details" open>
        <summary>What this group does &amp; how to use this dashboard</summary>

        <div className="detail-section">
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
        </div>

        <div className="detail-section">
          <h3>The agent team</h3>
          <p className="detail-lead">
            One orchestrator coordinates these specialist subagents. Steps marked{' '}
            <span className="gate-badge sm">⛔ Gate</span> always pause for a human before anything
            happens.
          </p>
          <div className="agent-list">
            {group.agents.map((a) => (
              <div key={a} className={`agent-row ${isGateAgent(a) ? 'is-gate' : ''}`}>
                <span className="agent-name">{humanizeAgent(a)}</span>
                {isGateAgent(a) && <span className="gate-badge">⛔ Approval gate</span>}
              </div>
            ))}
          </div>
        </div>

        <div className="detail-section">
          <h3>Connects to</h3>
          <div className="tile-portals">
            {group.portals.map((pid) => {
              const portal = PORTALS_BY_ID[pid]
              return (
                <span key={pid} className="portal-pill">
                  <span aria-hidden="true">{portal?.icon}</span> {portal?.name}
                </span>
              )
            })}
          </div>
        </div>

        <div className="detail-section">
          <h3>How to use this dashboard</h3>
          <ol className="howto">
            <li>
              <strong>Enter your inputs.</strong> Each panel below tells you what it does — fill its
              fields, then start the task.
            </li>
            <li>
              <strong>Watch it run.</strong> The orchestrator fans work out to the subagents above and
              streams their progress live.
            </li>
            <li>
              <strong>Approve &amp; ship.</strong> Anything consequential lands in your approvals queue.
              Nothing posts, pays, trades, lends, or files until you say so.
            </li>
          </ol>
        </div>
      </details>
    </section>
  )
}
