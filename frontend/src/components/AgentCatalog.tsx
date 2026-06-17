// Agent Catalog — tiles for organisations → agent groups → the agents inside
// each group. Deploy a group in one click (asks for portal API keys), or open
// its live dashboard.

import { useState } from 'react'
import { GROUPS_BY_ID, ORGANISATIONS, PORTALS_BY_ID, groupsForOrg, humanizeAgent, type AgentGroup } from '../lib/catalog'
import { usePlatformStore } from '../lib/deployments'
import { AgentGroupDetail } from './AgentGroupDetail'
import { DeployModal } from './DeployModal'

export interface AgentCatalogProps {
  /** Navigate to a group's dashboard view. */
  onOpen: (page: string) => void
}

export function AgentCatalog({ onOpen }: AgentCatalogProps) {
  const { deployments, connections, undeployGroup } = usePlatformStore()
  const [deploying, setDeploying] = useState<AgentGroup | null>(null)
  const [detail, setDetail] = useState<AgentGroup | null>(null)

  return (
    <div className="catalog">
      <header className="page-intro">
        <h1>Agent Catalog</h1>
        <p>
          Browse the agent organisations, the groups within them, and the agents inside each group.
          Click any card to see what it can do and how to use it — or deploy in one click.
        </p>
      </header>

      {ORGANISATIONS.map((org) => {
        const groups = groupsForOrg(org.id)
        const live = groups.filter((g) => deployments[g.id]).length
        return (
          <section key={org.id} aria-label={org.name} className="org-block">
            <div className="org-head">
              <span className="org-ico" aria-hidden="true">
                {org.icon}
              </span>
              <div className="org-titles">
                <h2>{org.name}</h2>
                <p>{org.tagline}</p>
              </div>
              <span className="tag">
                {live}/{groups.length} deployed
              </span>
            </div>

            <div className="tile-grid">
              {groups.map((g) => {
                const deployed = Boolean(deployments[g.id])
                const ready = g.portals.every((p) => connections[p])
                return (
                  <article key={g.id} className={`tile ${deployed ? 'tile-live' : ''}`}>
                    <button
                      type="button"
                      className="tile-open"
                      onClick={() => setDetail(g)}
                      aria-label={`What can ${g.title} do?`}
                    >
                      <div className="tile-top">
                        <span className="tile-ico" aria-hidden="true">
                          {g.icon}
                        </span>
                        <div className="tile-titles">
                          <h3>{g.title}</h3>
                          <span className="muted">{g.agents.length} agents</span>
                        </div>
                        <span className={`status-dot ${deployed ? 'on' : ready ? 'ready' : 'off'}`} aria-hidden="true" />
                      </div>

                      <p className="tile-blurb">{g.blurb}</p>

                      <div className="chip-row">
                        {g.agents.slice(0, 3).map((a) => (
                          <span key={a} className="chip">
                            {humanizeAgent(a)}
                          </span>
                        ))}
                        {g.agents.length > 3 && <span className="chip chip-more">+{g.agents.length - 3} more</span>}
                      </div>

                      <span className="tile-hint">What it does &amp; how to use it →</span>
                    </button>

                    <div className="tile-portals">
                      {g.portals.map((pid) => {
                        const portal = PORTALS_BY_ID[pid]
                        const on = Boolean(connections[pid])
                        return (
                          <span key={pid} className={`portal-pill ${on ? 'on' : ''}`} title={portal?.name}>
                            <span aria-hidden="true">{portal?.icon}</span> {portal?.name}
                          </span>
                        )
                      })}
                    </div>

                    <footer className="tile-foot">
                      {deployed ? (
                        <>
                          <span className="tag tag-ok">● Live</span>
                          {g.page && (
                            <button type="button" className="btn sm" onClick={() => onOpen(g.page as string)}>
                              Open
                            </button>
                          )}
                          <button type="button" className="btn sm ghost" onClick={() => undeployGroup(g.id)}>
                            Undeploy
                          </button>
                        </>
                      ) : (
                        <>
                          <button type="button" className="btn sm" onClick={() => setDeploying(g)}>
                            Deploy
                          </button>
                          {g.page ? (
                            <button type="button" className="btn sm ghost" onClick={() => onOpen(g.page as string)}>
                              Preview
                            </button>
                          ) : (
                            <span className="tag">Dashboard soon</span>
                          )}
                        </>
                      )}
                    </footer>
                  </article>
                )
              })}
            </div>
          </section>
        )
      })}

      {detail && (
        <AgentGroupDetail
          group={detail}
          deployed={Boolean(deployments[detail.id])}
          connections={connections}
          onDeploy={(g) => {
            setDetail(null)
            setDeploying(g)
          }}
          onOpen={(p) => {
            setDetail(null)
            onOpen(p)
          }}
          onUndeploy={(id) => {
            undeployGroup(id)
            setDetail(null)
          }}
          onClose={() => setDetail(null)}
        />
      )}

      {deploying && (
        <DeployModal group={GROUPS_BY_ID[deploying.id]} onClose={() => setDeploying(null)} />
      )}
    </div>
  )
}
