// Client-side onboarding state: which portals the org has connected and which
// agent groups have been deployed. Persisted to localStorage so it survives
// reloads. This is the configuration layer — a production build wires these
// actions to a backend provisioning endpoint (see run.md §3); the shapes here
// are what that endpoint would receive.

import { useSyncExternalStore } from 'react'

const CONNECTIONS_KEY = 'finance.connections'
const DEPLOYMENTS_KEY = 'finance.deployments'

export interface PortalConnection {
  portalId: string
  values: Record<string, string>
  connectedAt: string
}

export interface Deployment {
  groupId: string
  approver: string
  portals: string[]
  deployedAt: string
}

type Connections = Record<string, PortalConnection>
type Deployments = Record<string, Deployment>

// ---- tiny external store ---------------------------------------------------

const listeners = new Set<() => void>()
let version = 0

function emit(): void {
  version += 1
  for (const l of listeners) l()
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = globalThis.localStorage?.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown): void {
  try {
    globalThis.localStorage?.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable — in-memory only for this session */
  }
}

// ---- reads -----------------------------------------------------------------

export function getConnections(): Connections {
  return read<Connections>(CONNECTIONS_KEY, {})
}

export function getDeployments(): Deployments {
  return read<Deployments>(DEPLOYMENTS_KEY, {})
}

export function isConnected(portalId: string): boolean {
  return Boolean(getConnections()[portalId])
}

export function isDeployed(groupId: string): boolean {
  return Boolean(getDeployments()[groupId])
}

// ---- writes ----------------------------------------------------------------

export function connectPortal(portalId: string, values: Record<string, string>): void {
  const next = { ...getConnections() }
  next[portalId] = { portalId, values, connectedAt: nowISO() }
  write(CONNECTIONS_KEY, next)
  emit()
}

export function disconnectPortal(portalId: string): void {
  const next = { ...getConnections() }
  delete next[portalId]
  write(CONNECTIONS_KEY, next)
  emit()
}

export function deployGroup(groupId: string, approver: string, portals: string[]): void {
  const next = { ...getDeployments() }
  next[groupId] = { groupId, approver, portals, deployedAt: nowISO() }
  write(DEPLOYMENTS_KEY, next)
  emit()
}

export function undeployGroup(groupId: string): void {
  const next = { ...getDeployments() }
  delete next[groupId]
  write(DEPLOYMENTS_KEY, next)
  emit()
}

function nowISO(): string {
  // Date is fine in the browser; guarded for non-DOM test envs.
  try {
    return new Date().toISOString()
  } catch {
    return ''
  }
}

// ---- react hook ------------------------------------------------------------

/** Subscribe a component to the store; returns the current snapshot. */
export function usePlatformStore() {
  useSyncExternalStore(subscribe, () => version, () => version)
  return {
    connections: getConnections(),
    deployments: getDeployments(),
    connectPortal,
    disconnectPortal,
    deployGroup,
    undeployGroup,
    isConnected,
    isDeployed,
  }
}
