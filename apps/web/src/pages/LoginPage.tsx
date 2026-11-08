import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../auth'
import { ErrorBox } from '../components'

/** Sign-in for the review workflow. The API endpoint is POST-only, which is
 * why visiting /api/v1/auth/login directly in a browser shows a 405 — this
 * page is the human entry point. */
export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-sm mx-auto px-4 py-16">
      <h1 className="text-xl font-bold">Sign in</h1>
      <p className="text-sm text-slate-500 mt-1 mb-6">
        For contributors and reviewers of the OpenAid data workflow. Public
        exploration needs no account.
      </p>
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}
      <form onSubmit={submit} className="space-y-4 border border-slate-200 rounded-lg bg-white p-6">
        <div>
          <label htmlFor="username" className="block text-xs font-semibold text-slate-600 mb-1">
            Username
          </label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="password" className="block text-xs font-semibold text-slate-600 mb-1">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-blue-700 text-white font-semibold px-4 py-2 text-sm hover:bg-blue-800 disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
