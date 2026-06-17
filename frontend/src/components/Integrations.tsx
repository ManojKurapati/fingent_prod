// Integrations hub — connect the portals the organisation already uses (ERP/GL,
// banking, market data, CRM, document stores, the model provider). Credentials
// are saved to the local config store; production forwards them to a secrets
// manager (see run.md §4).

import { useMemo, useState } from 'react'
import { PORTALS, type Portal } from '../lib/catalog'
import { usePlatformStore } from '../lib/deployments'
import { Modal } from './Modal'

export function Integrations() {
  const { connections, connectPortal, disconnectPortal } = usePlatformStore()
  const [editing, setEditing] = useState<Portal | null>(null)

  const categories = useMemo(() => {
    const map = new Map<string, Portal[]>()
    for (const p of PORTALS) {
      const list = map.get(p.category) ?? []
      list.push(p)
      map.set(p.category, list)
    }
    return [...map.entries()]
  }, [])

  const connectedCount = Object.keys(connections).length

  return (
    <div className="integrations">
      <header className="page-intro">
        <h1>Integrations</h1>
        <p>
          Connect the portals your organisation already runs. Agents call these through the
          connector layer; consequential actions still pause for human approval.
          <strong> {connectedCount}</strong> of {PORTALS.length} connected.
        </p>
      </header>

      {categories.map(([category, portals]) => (
        <section key={category} aria-label={category} className="org-block">
          <div className="org-head">
            <div className="org-titles">
              <h2>{category}</h2>
            </div>
          </div>
          <div className="tile-grid">
            {portals.map((p) => {
              const conn = connections[p.id]
              return (
                <article key={p.id} className={`tile portal-tile ${conn ? 'tile-live' : ''}`}>
                  <div className="tile-top">
                    <span className="tile-ico" aria-hidden="true">
                      {p.icon}
                    </span>
                    <div className="tile-titles">
                      <h3>{p.name}</h3>
                      <span className="muted">{p.category}</span>
                    </div>
                    <span className={`status-dot ${conn ? 'on' : 'off'}`} aria-hidden="true" />
                  </div>

                  {conn ? (
                    <p className="muted">Connected — credentials stored.</p>
                  ) : (
                    <p className="muted">Not connected.</p>
                  )}

                  <footer className="tile-foot">
                    {conn ? (
                      <>
                        <span className="tag tag-ok">● Connected</span>
                        <button type="button" className="btn sm ghost" onClick={() => setEditing(p)}>
                          Edit
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => disconnectPortal(p.id)}>
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <button type="button" className="btn sm" onClick={() => setEditing(p)}>
                        Connect
                      </button>
                    )}
                  </footer>
                </article>
              )
            })}
          </div>
        </section>
      ))}

      {editing && (
        <ConnectPortalModal
          portal={editing}
          initial={connections[editing.id]?.values}
          onClose={() => setEditing(null)}
          onSave={(vals) => {
            connectPortal(editing.id, vals)
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

interface ConnectPortalModalProps {
  portal: Portal
  initial?: Record<string, string>
  onClose: () => void
  onSave: (values: Record<string, string>) => void
}

function ConnectPortalModal({ portal, initial, onClose, onSave }: ConnectPortalModalProps) {
  const [values, setValues] = useState<Record<string, string>>(initial ?? {})
  const complete = portal.fields.every((f) => (values[f.key] ?? '').trim().length > 0)

  return (
    <Modal title={`Connect ${portal.name}`} subtitle={portal.category} onClose={onClose}>
      {portal.fields.map((f) => (
        <label key={f.key}>
          {f.label}
          <input
            type={f.secret ? 'password' : 'text'}
            placeholder={f.placeholder}
            value={values[f.key] ?? ''}
            onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
          />
        </label>
      ))}
      <p className="muted">Stored in this browser’s config. Wire to a secrets manager for production.</p>
      <div className="modal-actions">
        <button type="button" className="btn ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={!complete}
          onClick={() => onSave(values)}
        >
          Save connection
        </button>
      </div>
    </Modal>
  )
}
