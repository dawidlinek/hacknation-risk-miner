# Załącznik: licencje bibliotek frontendu (npm)

Wygenerowano narzędziem `license-checker-rseidelsohn` 5.0.1 (zależność deweloperska w `frontend/package.json`) w katalogu `frontend/`, 2026-11-21:

- `npx license-checker-rseidelsohn --summary` (wszystkie pakiety w `node_modules`, łącznie z narzędziami do budowania i testów),
- `npx license-checker-rseidelsohn --production --summary` oraz `--production --csv` (tylko zależności uruchomieniowe, czyli to, co trafia do paczki aplikacji).

## Podsumowanie: wszystkie pakiety

| Licencja | Liczba pakietów |
|---|---:|
| MIT | 443 |
| ISC | 93 |
| Apache-2.0 | 23 |
| BSD-3-Clause | 13 |
| BlueOak-1.0.0 | 12 |
| BSD-2-Clause | 7 |
| MPL-2.0 | 4 |
| MIT OR Apache-2.0 | 2 |
| OFL-1.1 | 2 |
| 0BSD | 2 |
| (MIT OR CC0-1.0) | 2 |
| (MIT OR Apache-2.0) | 1 |
| Python-2.0 | 1 |
| CC-BY-4.0 | 1 |
| UNLICENSED | 1 |
| Unlicense | 1 |
| CC-BY-3.0 | 1 |
| CC0-1.0 | 1 |
| (MIT AND CC-BY-3.0) | 1 |
| MIT AND ISC AND BSD-3-Clause | 1 |

## Podsumowanie: tylko produkcja (`--production`)

| Licencja | Liczba pakietów |
|---|---:|
| MIT | 167 |
| ISC | 23 |
| BSD-3-Clause | 9 |
| BSD-2-Clause | 3 |
| OFL-1.1 | 2 |
| Apache-2.0 | 2 |
| (MIT OR Apache-2.0) | 1 |
| UNLICENSED | 1 |
| Unlicense | 1 |
| 0BSD | 1 |
| MIT AND ISC AND BSD-3-Clause | 1 |

## Pozycje wymagające komentarza

| Pakiet | Licencja | Zakres | Komentarz |
|---|---|---|---|
| `ex-ante-frontend` | UNLICENSED | projekt | To sam projekt (`"private": true`, brak pola `license`); licencja repozytorium ustalana przy przekazaniu praw MFiPR. |
| `@fontsource/geist`, `@fontsource/geist-mono` | OFL-1.1 | produkcja | Licencja fontów, pozwala na osadzanie i redystrybucję. |
| `isbot` | Unlicense | produkcja | Domena publiczna. |
| `axe-core`, `@axe-core/playwright` | MPL-2.0 | dev | Testy dostępności (Playwright), nie trafia do paczki. |
| `lightningcss` | MPL-2.0 | dev | Narzędzie budowania CSS (Tailwind/Vite), nie trafia do paczki. |
| `caniuse-lite` | CC-BY-4.0 | dev | Dane przeglądarek dla narzędzi budowania. |
| `spdx-exceptions`, `spdx-ranges` | CC-BY-3.0 | dev | Dane SPDX używane przez sam license-checker. |
| `argparse` | Python-2.0 | dev | Licencja permisywna (PSF). |

Brak pakietów GPL, LGPL, AGPL, SSPL ani CC-BY-NC.

## Zależności produkcyjne (pełna lista, `--production --csv`)

| Pakiet | Licencja | Repozytorium |
|---|---|---|
| `@floating-ui/core@1.8.0` | MIT | https://github.com/floating-ui/floating-ui |
| `@floating-ui/dom@1.8.0` | MIT | https://github.com/floating-ui/floating-ui |
| `@floating-ui/react-dom@2.1.9` | MIT | https://github.com/floating-ui/floating-ui |
| `@floating-ui/utils@0.2.12` | MIT | https://github.com/floating-ui/floating-ui |
| `@fontsource/geist-mono@5.3.0` | OFL-1.1 | https://github.com/fontsource/font-files |
| `@fontsource/geist@5.3.0` | OFL-1.1 | https://github.com/fontsource/font-files |
| `@mapbox/jsonlint-lines-primitives@2.0.3` | MIT | https://github.com/mapbox/jsonlint |
| `@mapbox/point-geometry@1.1.0` | ISC | https://github.com/mapbox/point-geometry |
| `@mapbox/tiny-sdf@2.3.0` | BSD-2-Clause | https://github.com/mapbox/tiny-sdf |
| `@mapbox/unitbezier@0.0.1` | BSD-2-Clause | https://github.com/mapbox/unitbezier |
| `@mapbox/unitbezier@1.0.0` | BSD-2-Clause | https://github.com/mapbox/unitbezier |
| `@mapbox/vector-tile@3.0.0` | BSD-3-Clause | https://github.com/mapbox/vector-tile-js |
| `@maplibre/geojson-vt@6.3.3` | ISC | https://github.com/maplibre/geojson-vt |
| `@maplibre/maplibre-gl-style-spec@19.3.3` | ISC | https://github.com/maplibre/maplibre-gl-style-spec |
| `@maplibre/maplibre-gl-style-spec@26.9.0` | ISC | https://github.com/maplibre/maplibre-style-spec |
| `@maplibre/mlt@1.3.0` | (MIT OR Apache-2.0) | https://github.com/maplibre/maplibre-tile-spec |
| `@maplibre/vt-pbf@4.3.3` | MIT | https://github.com/maplibre/vt-pbf |
| `@napi-rs/canvas-linux-x64-gnu@1.2.0` | MIT | https://github.com/Brooooooklyn/canvas |
| `@napi-rs/canvas@1.2.0` | MIT | https://github.com/Brooooooklyn/canvas |
| `@radix-ui/number@1.1.3` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/primitive@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-accessible-icon@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-accordion@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-alert-dialog@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-arrow@1.1.17` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-aspect-ratio@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-avatar@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-checkbox@1.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-collapsible@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-collection@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-compose-refs@1.1.5` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-context-menu@2.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-context@1.3.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-dialog@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-direction@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-dismissable-layer@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-dropdown-menu@2.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-focus-guards@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-focus-scope@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-form@0.3.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-hover-card@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-id@1.1.4` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-label@2.1.17` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-menu@2.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-menubar@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-navigation-menu@1.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-one-time-password-field@0.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-password-toggle-field@0.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-popover@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-popper@1.4.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-portal@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-presence@1.1.11` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-primitive@2.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-progress@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-radio-group@1.5.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-roving-focus@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-scroll-area@1.4.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-select@2.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-separator@1.2.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-slider@1.6.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-slot@1.5.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-switch@1.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-tabs@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-toast@1.3.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-toggle-group@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-toggle@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-toolbar@1.2.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-tooltip@1.4.1` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-callback-ref@1.1.5` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-controllable-state@1.3.0` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-effect-event@0.0.5` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-escape-keydown@1.1.6` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-is-hydrated@0.1.3` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-layout-effect@1.1.4` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-previous@1.1.4` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-rect@1.1.4` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-use-size@1.1.5` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/react-visually-hidden@1.2.13` | MIT | https://github.com/radix-ui/primitives |
| `@radix-ui/rect@1.1.3` | MIT | https://github.com/radix-ui/primitives |
| `@reduxjs/toolkit@2.15.0` | MIT | https://github.com/reduxjs/redux-toolkit |
| `@standard-schema/spec@1.1.0` | MIT | https://github.com/standard-schema/standard-schema |
| `@standard-schema/utils@0.3.0` | MIT | https://github.com/standard-schema/standard-schema |
| `@tanstack/history@1.162.5` | MIT | https://github.com/TanStack/router |
| `@tanstack/query-core@5.108.2` | MIT | https://github.com/TanStack/query |
| `@tanstack/react-query@5.108.2` | MIT | https://github.com/TanStack/query |
| `@tanstack/react-router@1.170.46` | MIT | https://github.com/TanStack/router |
| `@tanstack/react-store@0.11.2` | MIT | https://github.com/TanStack/store |
| `@tanstack/react-table@8.21.3` | MIT | https://github.com/TanStack/table |
| `@tanstack/router-core@1.171.39` | MIT | https://github.com/TanStack/router |
| `@tanstack/store@0.11.2` | MIT | https://github.com/TanStack/store |
| `@tanstack/table-core@8.21.3` | MIT | https://github.com/TanStack/table |
| `@types/d3-array@3.2.2` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-color@3.1.3` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-ease@3.0.2` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-interpolate@3.0.4` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-path@3.1.1` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-scale@4.0.9` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-shape@3.2.0` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-time@3.0.4` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/d3-timer@3.0.2` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/geojson@7946.0.16` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/react-dom@19.3.0` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/react@19.3.0` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@types/use-sync-external-store@0.0.6` | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| `@vis.gl/react-maplibre@8.1.3` | MIT | https://github.com/visgl/react-map-gl |
| `aria-hidden@1.2.6` | MIT | https://github.com/theKashey/aria-hidden |
| `arr-union@3.1.0` | MIT | https://github.com/jonschlinkert/arr-union |
| `assign-symbols@1.0.0` | MIT | https://github.com/jonschlinkert/assign-symbols |
| `bidi-js@1.1.0` | MIT | https://github.com/lojjic/bidi-js |
| `bytewise-core@1.2.3` | MIT | https://github.com/deanlandolt/bytewise-core |
| `bytewise@1.1.0` | MIT | https://github.com/deanlandolt/bytewise |
| `class-variance-authority@0.7.1` | Apache-2.0 | https://github.com/joe-bell/cva |
| `clsx@2.1.1` | MIT | https://github.com/lukeed/clsx |
| `cn@0.5.2` | MIT | https://github.com/shadcn-ui/cn |
| `cookie-es@3.1.1` | MIT | https://github.com/unjs/cookie-es |
| `csstype@3.2.4` | MIT | https://github.com/frenic/csstype |
| `d3-array@2.12.1` | BSD-3-Clause | https://github.com/d3/d3-array |
| `d3-array@3.2.5` | ISC | https://github.com/d3/d3-array |
| `d3-color@3.1.1` | ISC | https://github.com/d3/d3-color |
| `d3-ease@3.0.2` | BSD-3-Clause | https://github.com/d3/d3-ease |
| `d3-format@3.1.3` | ISC | https://github.com/d3/d3-format |
| `d3-geo@3.1.2` | ISC | https://github.com/d3/d3-geo |
| `d3-interpolate@3.0.2` | ISC | https://github.com/d3/d3-interpolate |
| `d3-path@1.0.9` | BSD-3-Clause | https://github.com/d3/d3-path |
| `d3-path@3.1.1` | ISC | https://github.com/d3/d3-path |
| `d3-sankey@0.12.3` | BSD-3-Clause | https://github.com/d3/d3-sankey |
| `d3-scale@4.0.3` | ISC | https://github.com/d3/d3-scale |
| `d3-shape@1.3.7` | BSD-3-Clause | https://github.com/d3/d3-shape |
| `d3-shape@3.2.1` | ISC | https://github.com/d3/d3-shape |
| `d3-time-format@4.1.1` | ISC | https://github.com/d3/d3-time-format |
| `d3-time@3.1.1` | ISC | https://github.com/d3/d3-time |
| `d3-timer@3.0.2` | ISC | https://github.com/d3/d3-timer |
| `decimal.js-light@2.5.1` | MIT | https://github.com/MikeMcl/decimal.js-light |
| `dequal@2.0.3` | MIT | https://github.com/lukeed/dequal |
| `detect-node-es@1.1.0` | MIT | https://github.com/thekashey/detect-node |
| `earcut@3.2.4` | ISC | https://github.com/mapbox/earcut |
| `es-toolkit@1.53.2` | MIT | https://github.com/toss/es-toolkit |
| `eventemitter3@5.0.4` | MIT | https://github.com/primus/eventemitter3 |
| `ex-ante-frontend@0.1.0` | UNLICENSED |  |
| `extend-shallow@2.0.1` | MIT | https://github.com/jonschlinkert/extend-shallow |
| `extend-shallow@3.0.2` | MIT | https://github.com/jonschlinkert/extend-shallow |
| `get-nonce@1.0.1` | MIT | https://github.com/theKashey/get-nonce |
| `get-value@2.0.6` | MIT | https://github.com/jonschlinkert/get-value |
| `gl-matrix@3.4.4` | MIT | https://github.com/toji/gl-matrix |
| `immer@11.2.10` | MIT | https://github.com/immerjs/immer |
| `internmap@1.0.1` | ISC | https://github.com/mbostock/internmap |
| `internmap@2.0.3` | ISC | https://github.com/mbostock/internmap |
| `is-extendable@0.1.1` | MIT | https://github.com/jonschlinkert/is-extendable |
| `is-extendable@1.0.1` | MIT | https://github.com/jonschlinkert/is-extendable |
| `is-plain-object@2.0.4` | MIT | https://github.com/jonschlinkert/is-plain-object |
| `isbot@5.2.3` | Unlicense | https://github.com/omrilotan/isbot |
| `isobject@3.0.1` | MIT | https://github.com/jonschlinkert/isobject |
| `js-tokens@4.0.0` | MIT | https://github.com/lydell/js-tokens |
| `json-stringify-pretty-compact@3.0.0` | MIT | https://github.com/lydell/json-stringify-pretty-compact |
| `json-stringify-pretty-compact@4.0.0` | MIT | https://github.com/lydell/json-stringify-pretty-compact |
| `kdbush@4.1.0` | ISC | https://github.com/mourner/kdbush |
| `loose-envify@1.4.0` | MIT | https://github.com/zertosh/loose-envify |
| `lucide-react@1.77.0` | ISC | https://github.com/lucide-icons/lucide |
| `make-cancellable-promise@2.0.0` | MIT | https://github.com/wojtekmaj/make-cancellable-promise |
| `make-event-props@2.0.0` | MIT | https://github.com/wojtekmaj/make-event-props |
| `maplibre-gl@6.19.0` | BSD-3-Clause | https://github.com/maplibre/maplibre-gl-js |
| `merge-refs@2.0.1` | MIT | https://github.com/wojtekmaj/merge-refs |
| `minimist@1.2.8` | MIT | https://github.com/minimistjs/minimist |
| `murmurhash-js@1.0.0` | MIT | https://github.com/mikolalysenko/murmurhash-js |
| `openapi-fetch@0.17.0` | MIT | https://github.com/openapi-ts/openapi-typescript |
| `openapi-react-query@0.5.4` | MIT | https://github.com/openapi-ts/openapi-typescript |
| `openapi-typescript-helpers@0.1.0` | MIT | https://github.com/openapi-ts/openapi-typescript |
| `pbf@5.2.0` | BSD-3-Clause | https://github.com/mapbox/pbf |
| `pdfjs-dist@6.5.438` | Apache-2.0 | https://github.com/mozilla/pdf.js |
| `potpack@2.1.0` | ISC | https://github.com/mapbox/potpack |
| `protocol-buffers-schema@3.6.1` | MIT | https://github.com/mafintosh/protocol-buffers-schema |
| `quickselect@3.0.0` | ISC | https://github.com/mourner/quickselect |
| `radix-ui@1.8.1` | MIT | https://github.com/radix-ui/primitives |
| `react-dom@19.3.1` | MIT | https://github.com/react/react |
| `react-is@19.3.1` | MIT | https://github.com/react/react |
| `react-pdf@11.1.0` | MIT | https://github.com/wojtekmaj/react-pdf |
| `react-redux@9.3.1` | MIT | https://github.com/reduxjs/react-redux |
| `react-remove-scroll-bar@2.3.8` | MIT | https://github.com/theKashey/react-remove-scroll-bar |
| `react-remove-scroll@2.7.2` | MIT | https://github.com/theKashey/react-remove-scroll |
| `react-style-singleton@2.2.3` | MIT | https://github.com/theKashey/react-style-singleton |
| `react@19.3.1` | MIT | https://github.com/react/react |
| `recharts@3.11.0` | MIT | https://github.com/recharts/recharts |
| `redux-thunk@3.1.0` | MIT | https://github.com/reduxjs/redux-thunk |
| `redux@5.0.1` | MIT | https://github.com/reduxjs/redux |
| `require-from-string@2.0.2` | MIT | https://github.com/floatdrop/require-from-string |
| `reselect@5.2.0` | MIT | https://github.com/reduxjs/reselect |
| `rw@1.3.3` | BSD-3-Clause | https://github.com/mbostock/rw |
| `scheduler@0.28.0` | MIT | https://github.com/react/react |
| `seroval-plugins@1.8.0` | MIT | https://github.com/lxsmnsyc/seroval |
| `seroval@1.8.2` | MIT | https://github.com/lxsmnsyc/seroval |
| `set-value@2.0.1` | MIT | https://github.com/jonschlinkert/set-value |
| `sonner@2.0.8` | MIT | https://github.com/emilkowalski/sonner |
| `sort-asc@0.2.0` | MIT | https://github.com/jonschlinkert/sort-asc |
| `sort-desc@0.2.0` | MIT | https://github.com/jonschlinkert/sort-desc |
| `sort-object@3.0.3` | MIT | https://github.com/doowb/sort-object |
| `split-string@3.1.0` | MIT | https://github.com/jonschlinkert/split-string |
| `tailwind-merge@3.7.1` | MIT | https://github.com/dcastil/tailwind-merge |
| `three@0.128.0` | MIT | https://github.com/mrdoob/three.js |
| `tiny-invariant@1.3.3` | MIT | https://github.com/alexreardon/tiny-invariant |
| `tinyqueue@3.0.0` | ISC | https://github.com/mourner/tinyqueue |
| `tslib@2.9.1` | 0BSD | https://github.com/Microsoft/tslib |
| `typewise-core@1.2.0` | MIT | https://github.com/deanlandolt/typewise-core |
| `typewise@1.0.3` | MIT | https://github.com/deanlandolt/typewise |
| `union-value@1.0.1` | MIT | https://github.com/jonschlinkert/union-value |
| `use-callback-ref@1.3.3` | MIT | https://github.com/theKashey/use-callback-ref |
| `use-sidecar@1.1.3` | MIT | https://github.com/theKashey/use-sidecar |
| `use-sync-external-store@1.7.0` | MIT | https://github.com/react/react |
| `victory-vendor@37.4.1` | MIT AND ISC AND BSD-3-Clause | https://github.com/FormidableLabs/victory |
| `warning@4.0.3` | MIT | https://github.com/BerkeleyTrue/warning |
| `zod@4.6.7` | MIT | https://github.com/colinhacks/zod |
| `zustand@5.1.0` | MIT | https://github.com/pmndrs/zustand |
