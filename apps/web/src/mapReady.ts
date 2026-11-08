import type * as maplibregl from 'maplibre-gl'

/** Run ``fn`` once the MapLibre style is actually ready for sources/layers.
 *
 * Only two signals are trustworthy:
 * - ``isStyleLoaded()`` — the style is operational right now; run immediately.
 * - ``loaded()`` — the map already completed its first full render (the
 *   ``load`` event fired earlier); run immediately.
 * Otherwise wait for ``load``, which fires exactly once after the first
 * render.
 *
 * The earlier ``styledata`` hook here was a bug: ``styledata`` fires on the
 * *initial* ``setStyle``, i.e. before the style is operational, so ``fn`` ran
 * too early, ``addSource`` half-registered sources whose tile managers never
 * spawned ("There is no tile manager with ID …"), and the canvas stayed blank
 * in every browser.
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
  if (map.isStyleLoaded() || map.loaded()) {
    run()
    return
  }
  map.once('load', run)
}
