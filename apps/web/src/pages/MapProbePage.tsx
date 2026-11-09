import { useEffect, useState } from 'react'
import * as maplibregl from 'maplibre-gl'

interface Diag {
  rafFired: boolean | null
  loaded: boolean | null
  styleLoaded: boolean | null
  sources: string[] | null
  layers: string[] | null
  mapErrors: string[]
  windowErrors: string[]
  webgl: string | null
}

/** Diagnostics page: creates the same map as /map and reports its state as
 * plain text (no canvas rendering required) so problems can be reported
 * from any browser. */
export default function MapProbePage() {
  const [diag, setDiag] = useState<Diag | null>(null)

  useEffect(() => {
    const mapErrors: string[] = []
    const windowErrors: string[] = []
    const onWinErr = (e: ErrorEvent) => windowErrors.push(e.message)
    window.addEventListener('error', onWinErr)

    const container = document.getElementById('probe-map')
    if (!container) {
      setDiag({ rafFired: null, loaded: null, styleLoaded: null, sources: null, layers: null, mapErrors: ['no #probe-map'], windowErrors, webgl: null })
      return
    }

    let webgl: string | null = null
    try {
      const testCanvas = document.createElement('canvas')
      const gl = testCanvas.getContext('webgl2') ?? testCanvas.getContext('webgl')
      webgl = gl ? String(gl.getParameter(gl.RENDERER)) : 'unavailable'
    } catch (err) {
      webgl = `error: ${String(err)}`
    }

    let map: maplibregl.Map
    try {
      map = new maplibregl.Map({
        container,
        style: {
          version: 8,
          sources: {},
          layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e8eef4' } }],
        },
        center: [18, 2],
        zoom: 2,
      })
    } catch (err) {
      setDiag({ rafFired: null, loaded: null, styleLoaded: null, sources: null, layers: null, mapErrors: [`constructor: ${String(err)}`], windowErrors, webgl })
      return
    }

    map.on('error', (e) => {
      mapErrors.push(e?.error?.message ?? 'unknown map error')
    })

    let rafFired: boolean | null = null
    requestAnimationFrame(() => {
      rafFired = true
    })
    window.setTimeout(() => {
      if (rafFired === null) {
        rafFired = false
      }
    }, 2500)

    window.setTimeout(() => {
      let sources: string[] | null = null
      let layers: string[] | null = null
      try {
        sources = Object.keys(map.getStyle()?.sources ?? {})
        layers = (map.getStyle()?.layers ?? []).map((l) => l.id)
      } catch (err) {
        mapErrors.push(`getStyle: ${String(err)}`)
      }
      setDiag({
        rafFired,
        loaded: map.loaded(),
        styleLoaded: map.isStyleLoaded(),
        sources,
        layers,
        mapErrors,
        windowErrors,
        webgl,
      })
    }, 6000)

    return () => {
      window.removeEventListener('error', onWinErr)
      map.remove()
    }
  }, [])

  return (
    <div className="max-w-3xl mx-auto px-4 py-10">
      <h1 className="text-xl font-bold">Map diagnostics</h1>
      <p className="text-sm text-slate-500 mt-1 mb-4">
        Share the block below verbatim when reporting a map problem.
      </p>
      <div id="probe-map" style={{ width: 10, height: 10, position: 'absolute', opacity: 0.01 }} />
      <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 text-xs overflow-x-auto whitespace-pre-wrap">
{diag ? JSON.stringify(diag, null, 2) : 'collecting… (results appear after ~6 seconds)'}
      </pre>
    </div>
  )
}
