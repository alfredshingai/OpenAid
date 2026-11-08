import type { FeatureCollection } from 'geojson'
import * as maplibregl from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Country } from '../api'
import { ErrorBox, Spinner } from '../components'

/** Africa-wide map: markers for every supported country (status-coloured),
 * real boundaries and choropleth for onboarded countries. */
export default function MapPage() {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapObj = useRef<maplibregl.Map | null>(null)
  const [countries, setCountries] = useState<Country[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Country | null>(null)
  const [level, setLevel] = useState(1)

  useEffect(() => {
    api.countries().then(setCountries).catch((e) => setError(String(e.message)))
  }, [])

  useEffect(() => {
    if (!mapRef.current || mapObj.current) return
    mapObj.current = new maplibregl.Map({
      container: mapRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e8eef4' } }],
      },
      center: [18, 2],
      zoom: 2.4,
    })
    mapObj.current.addControl(new maplibregl.NavigationControl())
    return () => mapObj.current?.remove()
  }, [])

  // markers for all countries
  useEffect(() => {
    const map = mapObj.current
    if (!map || !countries) return
    const fc: FeatureCollection = {
      type: 'FeatureCollection',
      features: countries
        .filter((c) => c.rep_lon !== null && c.rep_lat !== null)
        .map((c) => ({
          type: 'Feature' as const,
          geometry: {
            type: 'Point' as const,
            coordinates: [Number(c.rep_lon), Number(c.rep_lat)],
          },
          properties: {
            iso3: c.iso3,
            name: c.name,
            status: c.status,
            units: c.total_units,
          },
        })),
    }
    const addLayers = () => {
      map.addSource('countries', { type: 'geojson', data: fc })
      map.addLayer({
        id: 'country-dots',
        type: 'circle',
        source: 'countries',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'status'], 'active'], 9, 5],
          'circle-color': ['case', ['==', ['get', 'status'], 'active'], '#1d4ed8', '#94a3b8'],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        },
      })
      map.on('click', 'country-dots', (e: maplibregl.MapLayerMouseEvent) => {
        const f = e.features?.[0]
        if (!f) return
        const c = countries.find((x) => x.iso3 === f.properties?.iso3)
        if (c) setSelected(c)
      })
      map.on('mouseenter', 'country-dots', () => (map.getCanvas().style.cursor = 'pointer'))
      map.on('mouseleave', 'country-dots', () => (map.getCanvas().style.cursor = ''))
    }
    if (map.isStyleLoaded()) addLayers()
    else map.on('load', addLayers)
  }, [countries])

  // boundaries for the selected onboarded country
  useEffect(() => {
    const map = mapObj.current
    if (!map || !selected) return
    if (selected.status !== 'active') return
    let cancelled = false
    api.boundaries(selected.iso3, level).then((fc) => {
      if (cancelled) return
      if (map.getLayer('admin-fill')) map.removeLayer('admin-fill')
      if (map.getLayer('admin-line')) map.removeLayer('admin-line')
      if (map.getSource('admin')) map.removeSource('admin')
      map.addSource('admin', { type: 'geojson', data: fc })
      map.addLayer({
        id: 'admin-fill',
        type: 'fill',
        source: 'admin',
        paint: { 'fill-color': '#1d4ed8', 'fill-opacity': 0.18 },
      })
      map.addLayer({
        id: 'admin-line',
        type: 'line',
        source: 'admin',
        paint: { 'line-color': '#1d4ed8', 'line-width': 1.6 },
      })
      const xs: number[] = []
      const ys: number[] = []
      for (const f of fc.features) {
        const ring = (f.geometry as import('geojson').Polygon).coordinates[0]
        for (const [x, y] of ring) {
          xs.push(x)
          ys.push(y)
        }
      }
      if (xs.length) {
        map.fitBounds(
          [
            [Math.min(...xs), Math.min(...ys)],
            [Math.max(...xs), Math.max(...ys)],
          ],
          { padding: 60, duration: 500 },
        )
      }
    })
    return () => {
      cancelled = true
    }
  }, [selected, level])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!countries) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h1 className="text-lg font-bold">Africa-wide map</h1>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-blue-700 mr-1" />data onboarded</span>
          <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-slate-400 mr-1" />placeholder (no data yet)</span>
        </div>
        {selected?.status === 'active' && (
          <select
            className="ml-auto border border-slate-300 rounded px-2 py-1 text-sm"
            value={level}
            onChange={(e) => setLevel(Number(e.target.value))}
          >
            {selected.levels.map((l) => (
              <option key={l.level_number} value={l.level_number}>
                L{l.level_number} · {l.level_name} ({l.unit_count})
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="grid lg:grid-cols-[1fr_280px] gap-4">
        <div ref={mapRef} className="h-[540px] rounded-lg border border-slate-200" />
        <aside className="text-sm">
          {!selected ? (
            <div className="border border-slate-200 rounded-lg p-4 bg-white text-slate-500">
              Click a country marker. Onboarded countries show real administrative
              boundaries; placeholders explain what is missing.
            </div>
          ) : (
            <div className="border border-slate-200 rounded-lg p-4 bg-white space-y-2">
              <div className="font-semibold text-base">{selected.name}</div>
              <div className="text-xs text-slate-500">{selected.iso3} · {selected.region}</div>
              <div className="text-xs">
                Status: <b>{selected.status}</b>
                {selected.status === 'placeholder' && (
                  <span className="text-slate-500"> — administrative hierarchy and
                  boundaries not yet onboarded; structure exists, data follows the
                  country onboarding workflow.</span>
                )}
              </div>
              {selected.status === 'active' && (
                <>
                  <div className="text-xs text-slate-600">
                    {selected.max_level} administrative levels · {selected.total_units} units
                  </div>
                  <Link
                    to={`/countries/${selected.iso3}`}
                    className="inline-block mt-1 text-blue-700 font-semibold hover:underline"
                  >
                    Open country profile →
                  </Link>
                </>
              )}
            </div>
          )}
          <p className="mt-4 text-[11px] text-slate-400 leading-snug">
            Marker positions are approximate representative points used for
            display only — boundaries are the authoritative geometry.
          </p>
        </aside>
      </div>
    </div>
  )
}
