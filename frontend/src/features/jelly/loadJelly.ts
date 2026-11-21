/**
 * Lazy loader for the jelly renderer (design/assets/jelly-scene.js, ZgraiJelly overlay on three r128).
 * Both are decorative: nothing loads under reduced motion or without WebGL, and every failure resolves to false.
 */

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return true
  }
}

export function webglOk(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl'))
  } catch {
    return false
  }
}

/** A colour token as a hex string (the renderer needs a literal colour, not a CSS variable). */
export function tokenColor(name: string, fallback: string): string {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return /^#[0-9a-f]{3,8}$/i.test(v) ? v : fallback
  } catch {
    return fallback
  }
}

let loading: Promise<boolean> | null = null

/** Loads three and the renderer once per page; true when window.ZgraiJelly is ready. */
export function loadJelly(): Promise<boolean> {
  if (!loading) {
    loading = (async () => {
      if (!webglOk()) return false
      const THREE = await import('three')
      window.THREE = THREE
      await import('./jelly-scene.js')
      return !!window.ZgraiJelly
    })().catch(() => false)
  }
  return loading
}
