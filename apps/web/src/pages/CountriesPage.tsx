import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Country } from '../api'
import { ErrorBox, Spinner, StatusChip } from '../components'

export default function CountriesPage() {
  const [countries, setCountries] = useState<Country[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [onlyActive, setOnlyActive] = useState(false)

  useEffect(() => {
    api.countries().then(setCountries).catch((e) => setError(String(e.message)))
  }, [])

  const filtered = useMemo(() => {
    if (!countries) return []
    return countries.filter((c) => {
      if (onlyActive && c.status !== 'active') return false
      const q = query.trim().toLowerCase()
      if (!q) return true
      return c.name.toLowerCase().includes(q) || c.iso3.toLowerCase().includes(q)
    })
  }, [countries, query, onlyActive])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!countries) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">Countries</h1>
      <p className="text-sm text-slate-500 mt-1">
        Every African country is structurally supported. “Placeholder” means the
        onboarding workflow has not published validated data yet.
      </p>
      <div className="mt-4 flex gap-2 items-center">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name or ISO code…"
          className="border border-slate-300 rounded-md px-3 py-2 text-sm w-72"
        />
        <label className="text-xs text-slate-600 flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={onlyActive}
            onChange={(e) => setOnlyActive(e.target.checked)}
          />
          Only countries with data
        </label>
      </div>

      <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((c) => (
          <Link
            key={c.iso3}
            to={`/countries/${c.iso3}`}
            className="border border-slate-200 rounded-lg p-4 bg-white hover:border-blue-400 transition"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold">{c.name}</span>
              <StatusChip status={c.status} />
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {c.iso3} · {c.region ?? '—'} ·{' '}
              {c.max_level > 0 ? `${c.max_level} levels / ${c.total_units} units` : 'no data yet'}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
