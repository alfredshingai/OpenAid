import type { FeatureCollection } from 'geojson'
import * as maplibregl from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Country } from '../api'
import { ErrorBox, Spinner } from '../components'
import { whenMapReady } from '../mapReady'

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
    try {
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
      ;(window as unknown as Record<string, unknown>).__africaMap = mapObj.current

      // Some embedded viewers suspend requestAnimationFrame when the pane is
      // not composited, stalling MapLibre's render loop (blank canvas). Nudge
      // repaints on a timer until the map reports loaded; harmless elsewhere.
      const map = mapObj.current
      const repaintTimer = window.setInterval(() => {
        try {
          if (map.loaded()) {
            window.clearInterval(repaintTimer)
            return
          }
          map.triggerRepaint()
        } catch {
          window.clearInterval(repaintTimer)
        }
      }, 400)

      return () => {
        window.clearInterval(repaintTimer)
        // Null the ref on teardown: React StrictMode mounts effects twice, and
        // a stale removed-map reference made the re-run skip map creation.
        mapObj.current?.remove()
        mapObj.current = null
      }
    } catch (err) {
      setError(`Map failed to start: ${String(err)}`)
    }
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
      try {
      // Idempotent: StrictMode double-fires effects, so update in place
      // when the source already exists instead of re-adding it.
      const existing = map.getSource('countries') as maplibregl.GeoJSONSource | undefined
      if (existing) {
        existing.setData(fc)
        return
      }
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
      } catch (err) {
        setError(`Map layer failed: ${String(err)}`)
      }
    }
    whenMapReady(map, addLayers)
  }, [countries])

  // keep markers on top of outlines once both exist
  useEffect(() => {
    const map = mapObj.current
    if (!map) return
    const raise = () => {
      if (map.getLayer('country-dots') && map.getLayer('outline-fill')) {
        map.moveLayer('country-dots')
      }
    }
    map.on('sourcedata', raise)
    return () => {
      map.off('sourcedata', raise)
    }
  }, [])

  useEffect(() => {
    const map = mapObj.current
    if (!map) return
    let cancelled = false
    const draw = () => {
      fetch('/api/v1/boundaries/admin0')
        .then((r) => r.json())
        .then((fc) => {
          if (cancelled) return
          const existing = map.getSource('outlines') as maplibregl.GeoJSONSource | undefined
          if (existing) {
            existing.setData(fc)
            return
          }
          map.addSource('outlines', { type: 'geojson', data: fc })
          map.addLayer({
            id: 'outline-fill',
            type: 'fill',
            source: 'outlines',
            paint: {
              'fill-color': ['case', ['==', ['get', 'status'], 'active'], '#1d4ed8', '#b7c2cf'],
              'fill-opacity': ['case', ['==', ['get', 'status'], 'active'], 0.3, 0.45],
            },
          })
          map.addLayer({
            id: 'outline-line',
            type: 'line',
            source: 'outlines',
            paint: {
              'line-color': ['#1d4ed8', '#7d8da1'][0],
              'line-width': 1.1,
            },
          })
          map.on('click', 'outline-fill', (e: maplibregl.MapLayerMouseEvent) => {
            const iso3 = e.features?.[0]?.properties?.iso3
            if (!iso3 || !countries) return
            const c = countries.find((x) => x.iso3 === iso3)
            if (c) setSelected(c)
          })
          map.on('mouseenter', 'outline-fill', () => (map.getCanvas().style.cursor = 'pointer'))
          map.on('mouseleave', 'outline-fill', () => (map.getCanvas().style.cursor = ''))
        })
        .catch((err) => setError(`Outline layer failed: ${String(err)}`))
    }
    whenMapReady(map, draw)
    return () => {
      cancelled = true
    }
  }, [countries])

  // boundaries for the selected onboarded country
  useEffect(() => {
    const map = mapObj.current
    if (!map || !selected) return
    if (selected.status !== 'active') return
    let cancelled = false
    const draw = () => {
      api.boundaries(selected.iso3, level).then((fc) => {
        if (cancelled) return
        try {
          if (map.getLayer('admin-fill')) map.removeLayer('admin-fill')
          if (map.getLayer('admin-line')) map.removeLayer('admin-line')
          if (map.getSource('admin')) map.removeSource('admin')
          map.addSource('admin', { type: 'geojson', data: fc })
          map.addLayer({
            id: 'admin-fill',
            type: 'fill',
            source: 'admin',
            paint: { 'fill-color': '#1d4ed8', 'fill-opacity': 0.2 },
          })
          map.addLayer({
            id: 'admin-line',
            type: 'line',
            source: 'admin',
            paint: { 'line-color': '#1e40af', 'line-width': 1.8 },
          })
          // Loop-based bounds: handles Polygon AND MultiPolygon, and avoids
          // spreading tens of thousands of coordinates into Math.min/max.
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
          for (const f of fc.features) {
            const geom = f.geometry as import('geojson').Polygon | import('geojson').MultiPolygon
            const polygons = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates
            for (const polygon of polygons) {
              for (const [x, y] of polygon[0]) {
                if (x < minX) minX = x
                if (y < minY) minY = y
                if (x > maxX) maxX = x
                if (y > maxY) maxY = y
              }
            }
          }
          if (minX !== Infinity) {
            map.fitBounds(
              [
                [minX, minY],
                [maxX, maxY],
              ],
              { padding: 60, duration: 500 },
            )
          }
        } catch (err) {
          setError(`Boundary layer failed: ${String(err)}`)
        }
      }).catch((err) => setError(`Boundary data failed: ${String(err)}`))
    }
    whenMapReady(map, draw)
    return () => {
      cancelled = true
    }
  }, [selected, level])

  // The map container MUST stay mounted from the first render: the init
  // effect runs once, and a conditional Spinner here used to leave the ref
  // null at effect time — the map was then never created.
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
        <div className="relative">
          <div ref={mapRef} className="h-[540px] rounded-lg border border-slate-200" />
          {(error || !countries) && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-50/80 rounded-lg">
              {error ? <ErrorBox message={error} /> : <Spinner />}
            </div>
          )}
        </div>
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
