// Auth stub — FROZEN CONTRACT (shape, not implementation).
//
// A placeholder for OIDC/SSO. Holds a bearer token in memory (and localStorage
// when available) and exposes the header helper the API client uses. Wave 2/3
// build dashboards against this surface; production swaps the internals for a
// real identity provider without changing these signatures.

const STORAGE_KEY = 'finance.auth.token'

function readInitial(): string | null {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? null
  } catch {
    return null
  }
}

let token: string | null = readInitial()

export function login(newToken: string): void {
  token = newToken
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, newToken)
  } catch {
    /* localStorage unavailable — in-memory only */
  }
}

export function logout(): void {
  token = null
  try {
    globalThis.localStorage?.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export function getToken(): string | null {
  return token
}

export function isAuthenticated(): boolean {
  return token !== null
}

export function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {}
}
