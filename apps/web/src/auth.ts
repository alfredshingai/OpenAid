// Session state for the review workflow: token + user in localStorage.

export interface AuthUser {
  id: string
  username: string
  display_name: string | null
  role: 'contributor' | 'reviewer' | 'admin'
}

const KEY = 'openaid_auth'

export interface Session {
  token: string
  user: AuthUser
}

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Session
    return parsed.token && parsed.user ? parsed : null
  } catch {
    return null
  }
}

export function setSession(session: Session): void {
  localStorage.setItem(KEY, JSON.stringify(session))
  window.dispatchEvent(new Event('openaid-auth'))
}

export function clearSession(): void {
  localStorage.removeItem(KEY)
  window.dispatchEvent(new Event('openaid-auth'))
}

export async function login(username: string, password: string): Promise<Session> {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(res.status === 401 ? 'Invalid username or password.' : `Login failed: ${detail}`)
  }
  const data = (await res.json()) as Session
  setSession(data)
  return data
}
