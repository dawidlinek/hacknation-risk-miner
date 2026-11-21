// Vite pre-bundles maplibre-gl, which breaks its default worker lookup (it asks for .vite/deps/maplibre-gl-worker.mjs).
// Hand the map our own copy of the library and point it at a bundled worker file.
import * as maplibregl from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

maplibregl.setWorkerUrl(workerUrl)

export { maplibregl }
