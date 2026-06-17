import { beforeEach, describe, expect, it } from 'vitest'
import {
  connectPortal,
  deployGroup,
  disconnectPortal,
  getConnections,
  getDeployments,
  isConnected,
  isDeployed,
  undeployGroup,
} from './deployments'

beforeEach(() => {
  globalThis.localStorage.clear()
})

describe('deployments store', () => {
  it('connects and disconnects a portal', () => {
    expect(isConnected('plaid')).toBe(false)
    connectPortal('plaid', { clientId: 'cid', secret: 's3cr3t' })
    expect(isConnected('plaid')).toBe(true)
    expect(getConnections().plaid.values.clientId).toBe('cid')

    disconnectPortal('plaid')
    expect(isConnected('plaid')).toBe(false)
  })

  it('deploys and undeploys an agent group', () => {
    expect(isDeployed('fpa')).toBe(false)
    deployGroup('fpa', 'cfo@firm.com', ['anthropic', 'netsuite'])
    expect(isDeployed('fpa')).toBe(true)

    const dep = getDeployments().fpa
    expect(dep.approver).toBe('cfo@firm.com')
    expect(dep.portals).toContain('netsuite')

    undeployGroup('fpa')
    expect(isDeployed('fpa')).toBe(false)
  })

  it('returns empty state when nothing is configured', () => {
    expect(getConnections()).toEqual({})
    expect(getDeployments()).toEqual({})
  })
})
