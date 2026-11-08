import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as echarts from 'echarts'
import * as maplibregl from 'maplibre-gl'
import type { FeatureCollection, Polygon, MultiPolygon } from 'geojson'
import { api, type Country, type Facility, type Observation, type Unit } from '../api'
import { ErrorBox, ObservationCard, Spinner, StatusChip } from '../components'
import { whenMapReady } from '../mapReady'

/** Country profile: interactive boundary map, dynamic hierarchy navigation
 * (labels come from the API, never from code), indicator cards with
 * provenance, facilities layer and a population chart. */
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
  const [populationSeries, setPopulationSeries] = useState<Observation[] | null>(null)

  useEffect(() => {
    api.countryIndicators(country.iso3).then(setObservations).catch(() => setObservations([]))
    api
      .countryFacilities(country.iso3, { limit: 2000 })
      .then((r) => setFacilities(r.facilities))
      .catch(() => setFacilities([]))
    // Full series for the chart: every unit-level observation travels with
    // its own provenance, which the chart caption reproduces.
    fetch(`/api/v1/countries/${country.iso3}/indicators/total_population`)
      .then((r) => r.json())
      .then((d) => setPopulationSeries(d.observations ?? []))
      .catch(() => setPopulationSeries([]))
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
    <div className="mt-6 space-y-8">
      <div className="grid lg:grid-cols-[1fr_300px] gap-4">
        <CountryMap
          country={country}
          selectedUnit={selectedUnit}
          facilities={facilities}
          onSelectUnit={setSelectedUnit}
        />
        <aside className="border border-slate-200 rounded-lg bg-white p-4">
          <HierarchyBrowser country={country} onSelect={setSelectedUnit} />
        </aside>
      </div>

      <section>
        <h2 className="text-lg font-bold">
          Baseline indicators
          {selectedUnit && (
            <span className="text-sm font-normal text-slate-500">
              {' '}— {selectedUnit.name} ({selectedUnit.level_name}){' '}
              <button className="text-blue-700 hover:underline" onClick={() => setSelectedUnit(null)}>
                clear
              </button>
            </span>
          )}
        </h2>
        {!observations ? (
          <Spinner />
        ) : (
          <div className="mt-3 grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {(selectedUnit ? unitObs : observations)?.map((o) => (
              <ObservationCard key={o.id} obs={o} />
            ))}
            {selectedUnit && !unitObs && <Spinner label="Loading unit indicators…" />}
          </div>
        )}
      </section>

      {populationSeries && populationSeries.length > 0 && (
        <PopulationChart series={populationSeries} />
      )}
    </div>
  )
}

/** Interactive map: boundaries at the chosen level, facility dots, and
 * click-to-select a unit (resolved against PostGIS data, not client geometry). */
function CountryMap({
  country,
  selectedUnit,
  facilities,
  onSelectUnit,
}: {
  country: Country
  selectedUnit: Unit | null
  facilities: Facility[] | null
  onSelectUnit: (u: Unit) => void
}) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<maplibregl.Map | null>(null)
  const [level, setLevel] = useState(country.max_level)
  const [mapError, setMapError] = useState<string | null>(null)

  useEffect(() => {
    if (!mapRef.current || mapObj.current) return
    mapObj.current = new maplibregl.Map({
      container: mapRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#eef2f6' } }],
      },
      center: [country.rep_lon ?? 0, country.rep_lat ?? 0],
      zoom: 6,
    })
    mapObj.current.addControl(new maplibregl.NavigationControl())
    return () => {
      mapObj.current?.remove()
      mapObj.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapObj.current
    if (!map) return
    let cancelled = false
    const draw = () => {
      api.boundaries(country.iso3, level).then((fc) => {
      if (cancelled || !mapObj.current) return
      const m = mapObj.current
      try {
      for (const layer of ['units-fill', 'units-line']) {
        if (m.getLayer(layer)) m.removeLayer(layer)
      }
      if (m.getSource('units')) m.removeSource('units')
      m.addSource('units', { type: 'geojson', data: fc })
      m.addLayer({
        id: 'units-fill',
        type: 'fill',
        source: 'units',
        paint: {
          'fill-color': '#1d4ed8',
          'fill-opacity': [
            'case',
            ['==', ['get', 'official_code'], selectedUnit?.official_code ?? ''],
            0.5,
            0.3,
          ],
        },
      })
      m.addLayer({
        id: 'units-line',
        type: 'line',
        source: 'units',
        paint: { 'line-color': '#1e40af', 'line-width': 2 },
      })
      m.on('click', 'units-fill', async (e) => {
        const code = e.features?.[0]?.properties?.official_code
        if (!code) return
        const units = await api.units(country.iso3, { level_number: level, limit: 2000 })
        const hit = units.find((u) => u.official_code === code)
        if (hit) onSelectUnit(hit)
      })
      m.on('mouseenter', 'units-fill', () => (m.getCanvas().style.cursor = 'pointer'))
      m.on('mouseleave', 'units-fill', () => (m.getCanvas().style.cursor = ''))

      // Loop-based bounds: spreading tens of thousands of coordinates into
      // Math.min/Math.max overflows the call stack on large countries.
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      for (const f of fc.features) {
        const geom = f.geometry as Polygon | MultiPolygon
        const rings = geom.type === 'Polygon' ? [geom.coordinates[0]] : geom.coordinates.map((p) => p[0])
        for (const ring of rings) {
          for (const [x, y] of ring) {
            if (x < minX) minX = x
            if (y < minY) minY = y
            if (x > maxX) maxX = x
            if (y > maxY) maxY = y
          }
        }
      }
      if (minX !== Infinity) {
        m.fitBounds(
          [
            [minX, minY],
            [maxX, maxY],
          ],
          { padding: 40, duration: 400 },
        )
      }
      } catch (err) {
        if (!cancelled) setMapError(`Boundary layer failed: ${String(err)}`)
      }
      }).catch((err) => {
        if (!cancelled) setMapError(`Boundary data failed: ${String(err)}`)
      })
    }
    whenMapReady(map, draw)
    return () => {
      cancelled = true
    }
  }, [country, level])

  useEffect(() => {
    const m = mapObj.current
    if (!m || !m.getLayer('units-fill')) return
    m.setPaintProperty('units-fill', 'fill-opacity', [
      'case',
      ['==', ['get', 'official_code'], selectedUnit?.official_code ?? ''],
      0.45,
      0.14,
    ])
  }, [selectedUnit])

  useEffect(() => {
    const m = mapObj.current
    if (!m || !facilities) return
    const pts: FeatureCollection = {
      type: 'FeatureCollection',
      features: facilities
        .filter((f) => f.lon !== undefined && f.lat !== undefined)
        .map((f) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [f.lon!, f.lat!] },
          properties: { name: f.name },
        })),
    }
    const add = () => {
      if (!m) return
      const src = m.getSource('facilities') as maplibregl.GeoJSONSource | undefined
      if (src) src.setData(pts)
      else {
        m.addSource('facilities', { type: 'geojson', data: pts })
        m.addLayer({
          id: 'facilities-dots',
          type: 'circle',
          source: 'facilities',
          paint: {
            'circle-radius': 3,
            'circle-color': '#e07b39',
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 0.8,
          },
        })
      }
    }
    whenMapReady(m, add)
  }, [facilities])

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <h2 className="text-lg font-bold">Map</h2>
        <select
          className="border border-slate-300 rounded px-2 py-1 text-xs"
          value={level}
          onChange={(e) => setLevel(Number(e.target.value))}
        >
          {country.levels.map((l) => (
            <option key={l.level_number} value={l.level_number}>
              L{l.level_number} · {l.level_name} ({l.unit_count})
            </option>
          ))}
        </select>
        {facilities && facilities.length > 0 && (
          <span className="text-[11px] text-slate-500">
            <span className="inline-block w-2 h-2 rounded-full bg-orange-500 mr-1" />
            {facilities.length} facilities
          </span>
        )}
      </div>
      {mapError && (
        <div className="mb-2 bg-amber-50 border border-amber-200 text-amber-800 rounded p-2 text-xs">
          {mapError}
        </div>
      )}
      <div ref={mapRef} className="h-[420px] rounded-lg border border-slate-200" />
      <p className="mt-1 text-[11px] text-slate-400">
        Click a unit to load its indicators · facility dots are a mapping
        signal, not proof of operation
      </p>
    </div>
  )
}

/** Bar chart: population per first-level unit, provenance in the caption. */
function PopulationChart({ series }: { series: Observation[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  const data = useMemo(() => {
    const byUnit = new Map<string, { name: string; value: number }>()
    for (const o of series) {
      if (o.value === null || !o.unit) continue
      if (o.unit.level_number !== 1) continue
      byUnit.set(o.unit.official_code, { name: o.unit.name, value: o.value })
    }
    return [...byUnit.values()].sort((a, b) => b.value - a.value)
  }, [series])

  useEffect(() => {
    if (!ref.current || !data.length) return
    chart.current?.dispose()
    chart.current = echarts.init(ref.current)
    chart.current.setOption({
      grid: { left: 150, right: 30, top: 10, bottom: 30 },
      xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      yAxis: { type: 'category', data: data.map((d) => d.name), axisLabel: { fontSize: 11 } },
      series: [
        {
          type: 'bar',
          data: data.map((d) => Math.round(d.value)),
          itemStyle: { color: '#1d4ed8', borderRadius: [0, 3, 3, 0] },
          barMaxWidth: 22,
          label: { show: true, position: 'right', fontSize: 10, formatter: (p: { value: number }) => p.value.toLocaleString('en-US') },
        },
      ],
      tooltip: { trigger: 'axis' },
    })
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.current?.dispose()
      chart.current = null
    }
  }, [data])

  if (!data.length) return null
  const meta = series.find((o) => o.unit && o.unit.level_number === 1)

  return (
    <section>
      <h2 className="text-lg font-bold">Population by first-level unit</h2>
      <div className="mt-3 border border-slate-200 rounded-lg bg-white p-4">
        <div ref={ref} className="h-[300px]" />
        {meta && (
          <p className="mt-2 text-[11px] text-slate-500">
            Source: {meta.source} ({meta.source_licence}) · period {meta.period_start.slice(0, 4)} ·
            value type: {meta.value_type} — {meta.methodology_notes ?? meta.methodology}
          </p>
        )}
      </div>
    </section>
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
  const [depth, setDepth] = useState(0)
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
      .units(country.iso3, {
        level_number: level.level_number,
        ...(parent ? { parent_code: parent.official_code } : {}),
      })
      .then(setChildren)
  }, [country, depth, path])

  const level = country.levels[depth]

  return (
    <div>
      <h2 className="font-semibold text-sm">Administrative hierarchy</h2>
      <div className="mt-1 text-[11px] text-slate-400">
        Labels come from each country's configuration — no hardcoded level names.
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
          Selected unit is at the deepest configured level: {path[path.length - 1]?.name}
        </p>
      ) : !children ? (
        <Spinner />
      ) : (
        <>
          <div className="mt-2 text-xs font-medium text-slate-600">
            {level.level_name}s ({children.length})
          </div>
          <ul className="mt-1 max-h-80 overflow-y-auto">
            {children.map((u) => (
              <li
                key={u.id}
                className="flex items-center justify-between gap-2 py-1 border-b border-slate-50"
              >
                <button
                  className={`text-left text-xs truncate ${
                    path.some((p) => p.id === u.id)
                      ? 'text-blue-700 font-semibold'
                      : 'text-slate-700'
                  } hover:text-blue-700`}
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
          {path.length > 0 && (
            <p className="mt-2 text-[11px] text-slate-500">
              Path: {path.map((p) => p.official_code).join(' → ')} — {path[path.length - 1].name}
            </p>
          )}
        </>
      )}
    </div>
  )
}
