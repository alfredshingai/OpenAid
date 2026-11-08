import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as maplibregl from 'maplibre-gl'
import { api, type Country, type Facility, type Observation, type Unit } from '../api'
import { ErrorBox, ObservationCard, Spinner, StatusChip, formatNumber } from '../components'

/** Country profile: dynamic hierarchy navigation (labels come from the API,
 * never from code), indicator cards with provenance, facility directory. */
export default function CountryPage() {
  const { iso3 = '' } = useParams()
  const [country, setCountry] = useState<Country | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setCountry(null)
    setError(null)
    api.country(iso3).then(setCountry).catch((e) => setError(String(e.message)))
  }, [iso3])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!country) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">{country.name}</h1>
        <StatusChip status={country.status} />
        <span className="text-xs text-slate-500">{country.iso3} · {country.region}</span>
      </div>

      {country.status === 'placeholder' ? (
        <PlaceholderNotice country={country} />
      ) : (
        <ActiveCountry country={country} />
      )}
    </div>
  )
}

function PlaceholderNotice({ country }: { country: Country }) {
  return (
    <div className="mt-6 border border-slate-200 rounded-lg bg-white p-6 text-sm text-slate-600 space-y-2">
      <p className="font-semibold text-slate-800">No data onboarded yet</p>
      <p>
        OpenAid's architecture supports {country.name} today, but no validated
        administrative boundaries or baseline indicators have been published
        through the country onboarding workflow. This status is shown
        deliberately — the platform never implies continental completeness.
      </p>
      <p className="text-xs text-slate-500">
        Contributors can start the onboarding workflow described in the
        repository documentation (country configuration → boundary acquisition
        with licence → validation → publication).
      </p>
    </div>
  )
}

function ActiveCountry({ country }: { country: Country }) {
  const [observations, setObservations] = useState<Observation[] | null>(null)
  const [selectedUnit, setSelectedUnit] = useState<Unit | null>(null)
  const [unitObs, setUnitObs] = useState<Observation[] | null>(null)
  const [facilities, setFacilities] = useState<Facility[] | null>(null)

  useEffect(() => {
    api.countryIndicators(country.iso3).then(setObservations).catch(() => setObservations([]))
    api.countryFacilities(country.iso3, { limit: 5 }).then((r) => setFacilities(r.facilities)).catch(() => setFacilities([]))
  }, [country])

  useEffect(() => {
    if (!selectedUnit) {
      setUnitObs(null)
      return
    }
    api
      .unitIndicators(country.iso3, selectedUnit.official_code)
      .then(setUnitObs)
      .catch(() => setUnitObs([]))
  }, [country, selectedUnit])

  return (
    <div className="mt-6 grid lg:grid-cols-[300px_1fr] gap-6">
      {/* Dynamic hierarchy browser */}
      <aside className="border border-slate-200 rounded-lg bg-white p-4">
        <HierarchyBrowser country={country} onSelect={setSelectedUnit} />
      </aside>

      <div className="space-y-8">
        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-bold">
              Baseline indicators
              {selectedUnit && (
                <span className="text-sm font-normal text-slate-500">
                  {' '}— {selectedUnit.name} ({selectedUnit.level_name}){' '}
                  <button
                    className="text-blue-700 hover:underline"
                    onClick={() => setSelectedUnit(null)}
                  >
                    clear
                  </button>
                </span>
              )}
            </h2>
          </div>
          {!observations ? (
            <Spinner />
          ) : (
            <div className="mt-3 grid sm:grid-cols-2 gap-3">
              {(selectedUnit ? unitObs : observations)?.map((o) => (
                <ObservationCard key={o.id} obs={o} />
              ))}
              {selectedUnit && !unitObs && <Spinner label="Loading unit indicators…" />}
            </div>
          )}
        </section>

        <section>
          <h2 className="text-lg font-bold">Facilities (sample)</h2>
          <p className="text-xs text-slate-500">
            Operational status is reported as stored — a facility present in a
            source dataset is not proof it currently operates.
          </p>
          {!facilities ? (
            <Spinner />
          ) : (
            <ul className="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg bg-white">
              {facilities.map((f) => (
                <li key={f.id} className="px-4 py-2.5 text-sm flex justify-between gap-4">
                  <span className="truncate">{f.name}</span>
                  <span className="text-xs text-slate-500 whitespace-nowrap">
                    {f.operational_status} · {f.source?.split(' ')[0]}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

/** Hierarchy navigation driven entirely by the country's configured levels. */
function HierarchyBrowser({
  country,
  onSelect,
}: {
  country: Country
  onSelect: (u: Unit) => void
}) {
  const [depth, setDepth] = useState(0) // index into levels
  const [path, setPath] = useState<Unit[]>([])
  const [children, setChildren] = useState<Unit[] | null>(null)

  useEffect(() => {
    setDepth(0)
    setPath([])
    setChildren(null)
  }, [country])

  useEffect(() => {
    const level = country.levels[depth]
    if (!level) {
      setChildren(null)
      return
    }
    const parent = path[depth - 1]
    api
      .units(country.iso3, { level_number: level.level_number, ...(parent ? { parent_code: parent.official_code } : {}) })
      .then(setChildren)
  }, [country, depth, path])

  const level = country.levels[depth]

  return (
    <div>
      <h2 className="font-semibold text-sm">Administrative hierarchy</h2>
      <div className="mt-1 text-[11px] text-slate-400">
        Labels are configured per country — this UI has no hardcoded level names.
      </div>
      {path.length > 0 && (
        <button
          className="mt-2 text-xs text-blue-700 hover:underline"
          onClick={() => {
            setPath(path.slice(0, -1))
            setDepth(depth - 1)
          }}
        >
          ← up one level
        </button>
      )}
      {!level ? (
        <p className="mt-3 text-xs text-slate-500">
          Selected unit is at the deepest configured level.
        </p>
      ) : !children ? (
        <Spinner />
      ) : (
        <>
          <div className="mt-2 text-xs font-medium text-slate-600">
            {level.level_name}s ({children.length})
          </div>
          <ul className="mt-1 max-h-96 overflow-y-auto">
            {children.map((u) => (
              <li key={u.id} className="flex items-center justify-between gap-2 py-1 border-b border-slate-50">
                <button
                  className="text-left text-xs text-slate-700 hover:text-blue-700 truncate"
                  onClick={() => onSelect(u)}
                  title={u.name}
                >
                  <b>{u.official_code}</b> {u.name}
                </button>
                {depth < country.max_level - 1 && (
                  <button
                    className="text-[11px] text-blue-700 hover:underline whitespace-nowrap"
                    onClick={() => {
                      setPath([...path.slice(0, depth), u])
                      setDepth(depth + 1)
                    }}
                  >
                    drill →
                  </button>
                )}
              </li>
            ))}
          </ul>
          {selectedSummary(path)}
        </>
      )}
    </div>
  )
}

function selectedSummary(path: Unit[]) {
  if (!path.length) return null
  const leaf = path[path.length - 1]
  return (
    <p className="mt-2 text-[11px] text-slate-500">
      Path: {path.map((p) => p.official_code).join(' → ')} — {leaf.name}
    </p>
  )
}

// Keep maplibre imported for potential detail map; avoid unused warning.
void maplibregl
void formatNumber
