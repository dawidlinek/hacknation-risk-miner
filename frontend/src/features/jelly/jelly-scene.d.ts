// Classic script (design/assets/jelly-scene.js): defines window.ZgraiJelly when window.THREE (r128) exists.
export {}

declare global {
  interface ZgraiJellyHandle {
    wake: () => void
    sleep: () => void
    refresh: () => void
    poke: () => void
    dispose: () => void
  }
  interface Window {
    THREE?: unknown
    ZgraiJelly?: {
      version: string
      mountOverlay: (
        canvas: HTMLCanvasElement,
        root: HTMLElement | null,
        options?: Record<string, unknown>,
      ) => ZgraiJellyHandle
    }
  }
}
