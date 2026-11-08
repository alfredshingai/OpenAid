import type * as maplibregl from 'maplibre-gl'

/** Run ``fn`` once the MapLibre style is actually ready.
 *
 * ``isStyleLoaded()`` is the only reliable immediate signal; the ``load``
 * event fires exactly once and is missed if registration happens late, and
 * ``styledata`` covers late style swaps. A ran-flag makes double firing
 * harmless. Without this helper, layers attached in the wrong window
 * silently never appear — the "map shows nothing" bug.
 */
export function whenMapReady(map: maplibregl.Map, fn: () => void): void {
  const run = (() => {
    let ran = false
    return () => {
      if (ran) return
      ran = true
      fn()
    }
  })()
  if (map.isStyleLoaded()) {
    run()
    return
  }
  map.once('load', run)
  map.once('styledata', run)
}
