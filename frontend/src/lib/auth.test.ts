import { beforeEach, describe, expect, it } from 'vitest'
import { authHeaders, getToken, isAuthenticated, login, logout } from './auth'

describe('auth stub', () => {
  beforeEach(() => logout())

  it('starts unauthenticated', () => {
    expect(isAuthenticated()).toBe(false)
    expect(getToken()).toBeNull()
    expect(authHeaders()).toEqual({})
  })

  it('stores a token on login and exposes a bearer header', () => {
    login('dev-token')
    expect(isAuthenticated()).toBe(true)
    expect(getToken()).toBe('dev-token')
    expect(authHeaders()).toEqual({ Authorization: 'Bearer dev-token' })
  })

  it('clears the token on logout', () => {
    login('x')
    logout()
    expect(isAuthenticated()).toBe(false)
  })
})
