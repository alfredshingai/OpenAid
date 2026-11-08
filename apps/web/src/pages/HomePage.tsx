import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api, type Country } from '../api'
import { ErrorBox, Spinner } from '../components'

export default function HomePage() {
  const [countries, setCountries] = useState<Country[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.countries().then(setCountries).catch((e) => setError(String(e.message)))
  }, [])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!countries) return <Spinner />

  const active = countries.filter((c) => c.status === 'active')
  const onboardedUnits = active.reduce((s, c) => s + c.total_units, 0)

  return (
    <div>
      <section className="bg-gradient-to-br from-blue-700 to-blue-900 text-white">
        <div className="max-w-6xl mx-auto px-4 py-16">
          <p className="text-blue-200 text-sm font-medium uppercase tracking-wide">
            Open-source humanitarian & community intelligence
          </p>
          <h1 className="mt-3 text-4xl font-bold leading-tight">
            Open data. Stronger communities.
            <br />
            Better decisions.
          </h1>
          <p className="mt-4 max-w-2xl text-blue-100">
            Explore Africa-wide administrative geography, baseline indicators,
            organisations and services — with the source, licence, date and
            method behind every figure.
          </p>
          <div className="mt-6 flex gap-3">
            <Link
              to="/map"
              className="rounded-md bg-white text-blue-800 font-semibold px-4 py-2 text-sm hover:bg-blue-50"
            >
              Explore the map
            </Link>
            <Link
              to="/countries"
              className="rounded-md border border-blue-300 text-white font-semibold px-4 py-2 text-sm hover:bg-blue-800"
            >
              Browse countries
            </Link>
          </div>
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-4 py-12 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Countries structurally supported" value={countries.length} />
        <Stat label="Countries with onboarded data" value={active.length} />
        <Stat label="Administrative units stored" value={onboardedUnits} />
        <Stat label="Datasets catalogued" value="4" href="/datasets" />
      </section>

      <section className="max-w-6xl mx-auto px-4 pb-16">
        <h2 className="text-lg font-bold mb-3">Onboarded countries</h2>
        {active.length === 0 ? (
          <p className="text-sm text-slate-500">
            No country data has been onboarded yet — coverage is progressive and
            honesty about gaps is part of the design.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {active.map((c) => (
              <Link
                key={c.iso3}
                to={`/countries/${c.iso3}`}
                className="border border-slate-200 rounded-lg p-4 bg-white hover:border-blue-400 transition"
              >
                <div className="font-semibold">{c.name}</div>
                <div className="text-xs text-slate-500 mt-1">
                  {c.iso3} · {c.max_level} admin levels · {c.total_units} units
                </div>
              </Link>
            ))}
          </div>
        )}
        <p className="mt-6 text-xs text-slate-500">
          All other countries appear as “placeholder”: the architecture supports
          them from day one, and data onboarding follows the documented country
          workflow. Placeholder status is shown everywhere, never hidden.
        </p>
      </section>
    </div>
  )
}

function Stat({ label, value, href }: { label: string; value: number | string; href?: string }) {
  const inner = (
    <div className="border border-slate-200 rounded-lg p-4 bg-white h-full">
      <div className="text-2xl font-bold text-blue-800">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  )
  return href ? (
    <Link to={href} className="hover:opacity-90">
      {inner}
    </Link>
  ) : (
    inner
  )
}
