/**
 * The shot list: every capture of the live app the video uses.
 * Responsibility: browser steps per shot (clicked by visible text, like a viewer would).
 * Shots marked `writes` change the live database; they skip the warm-up pass and are
 * listed in docs/submission/video/created_records.md.
 * `{AN}` in a path is replaced with the analysis code the `new` shot created.
 */
export type Target =
  | string // visible text: button name, link name, then exact text
  | { css: string }
  | { role: 'button' | 'link' | 'tab' | 'menuitem'; name: string; exact?: boolean };

export type Step =
  | 'mark'
  | { goto: string }
  | { wait: number }
  | { click: Target; nth?: number }
  | { fakeClick: Target } // cursor moves and "clicks" without a real click (file pickers)
  | { upload: { css: string; file: string; name?: string; appendByte?: boolean } }
  | { until: { text?: string; css?: string; url?: string; gone?: string }; cap?: number; record?: boolean; realtime?: boolean }
  | { scroll: { to: number | Target; ms: number; offset?: number } }
  | { hover: Target; ms?: number }
  | { saveAn: true };

export interface Shot {
  id: string;
  kind: 'video' | 'still';
  steps: Step[];
  /** Writes to the live database: no warm-up pass. */
  writes?: boolean;
  /** Still: capture the whole page height. */
  fullPage?: boolean;
  parked?: boolean;
}

const REPO = new URL('../../../../../', import.meta.url).pathname;
export const PFU = `${REPO}data/raw/docs_22/2026-11-21/RM-2026-013/files/9cdc085eedd413b1_PFU_Kaniów.pdf`;
export const ZAGRODNO = `${REPO}materials/organizer_cases/Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf`;

export const SHOTS: Shot[] = [
  {
    id: 'pulpit',
    kind: 'video',
    steps: [{ goto: '/' }, 'mark', { wait: 2500 }, { scroll: { to: 330, ms: 1600 } }, { wait: 1500 }],
  },
  // Path (b): a new investment, end to end. Creates one analysis on live.
  {
    id: 'new',
    kind: 'video',
    writes: true,
    steps: [
      { goto: '/analizy/nowa' },
      'mark',
      { wait: 400 },
      // the jelly builder bots only start when the pointer enters their scene
      { hover: { css: '[data-testid="jelly-site"]' }, ms: 2400 },
      // one click: example description + the example Kaniów PFU (consistent with each other since the lead's fix)
      { click: 'Wypełnij przykładem' },
      // the example upload fails under the frozen clock: run it on the real clock, off camera
      { until: { text: 'PFU, 76 s.' }, cap: 90_000, record: false, realtime: true },
      { wait: 1000 },
      { until: { text: 'Rozumiemy to tak' }, cap: 120_000, record: false, realtime: true },
      { until: { gone: 'Czytamy opis' }, cap: 120_000, record: false, realtime: true },
      { scroll: { to: 9999, ms: 1400 } },
      { wait: 2600 },
      { click: { role: 'button', name: 'Uruchom analizę' } },
      { until: { url: '/analizy/AN-' }, cap: 60_000, record: true },
      { saveAn: true },
      { until: { css: '[data-testid="question-cards"]' }, cap: 90_000, record: false },
      { wait: 3000 },
    ],
  },
  { id: 'report', kind: 'still', fullPage: true, steps: [{ goto: '/analizy/{AN}' }, { wait: 2500 }] },
  {
    id: 'redpen',
    kind: 'video',
    steps: [
      { goto: '/analizy/{AN}' },
      { click: { role: 'link', name: 'Czerwony długopis' } },
      { until: { css: '[data-testid="page-text"]' }, cap: 90_000 },
      { until: { gone: 'Model AI czyta dokument' }, cap: 120_000 },
      { wait: 1500 },
      'mark',
      { wait: 1500 },
      { click: { css: 'aside button[id^="u"]' } },
      { wait: 3500 },
      { click: { css: 'aside button[id^="u"]' }, nth: 1 },
      { wait: 3500 },
    ],
  },
  {
    id: 'sim',
    kind: 'video',
    steps: [
      { goto: '/analizy/{AN}/symulacja' },
      { wait: 2000 },
      'mark',
      { wait: 1500 },
      { scroll: { to: 'Co możesz zmienić przed przetargiem', ms: 1300, offset: -260 } },
      { click: { css: 'main label' }, nth: 1 },
      { wait: 500 },
      { scroll: { to: 0, ms: 1300 } },
      { wait: 2600 },
      { scroll: { to: 'Co możesz zmienić przed przetargiem', ms: 1300, offset: -260 } },
      { click: { css: 'main label' }, nth: 0 },
      { wait: 500 },
      { scroll: { to: 0, ms: 1300 } },
      { wait: 3000 },
    ],
  },
  {
    id: 'pakiet',
    kind: 'video',
    steps: [
      { goto: '/analizy/{AN}/pakiet' },
      { wait: 2000 },
      'mark',
      { wait: 2500 },
      { hover: { role: 'button', name: 'Pobierz DOCX' }, ms: 2500 },
      { hover: { role: 'button', name: 'PDF', exact: true }, ms: 2000 },
    ],
  },
  // Path (a): from the project record to the evidence.
  {
    id: 'projekty',
    kind: 'video',
    steps: [
      { goto: '/projekty' },
      { wait: 1500 },
      'mark',
      { wait: 2000 },
      { hover: { role: 'link', name: 'Budowa oczyszczalni ścieków w miejscowości Steklin w formule zaprojektuj i wybuduj' }, ms: 900 },
      { click: { role: 'link', name: 'Budowa oczyszczalni ścieków w miejscowości Steklin w formule zaprojektuj i wybuduj' } },
      { until: { text: 'CO SIĘ STAŁO' }, cap: 30_000 },
      { wait: 2500 },
    ],
  },
  { id: 'card', kind: 'still', fullPage: true, steps: [{ goto: '/projekty/RM-2026-003' }, { wait: 2500 }] },
  {
    id: 'chat',
    kind: 'video',
    steps: [
      { goto: '/projekty/RM-2026-003' },
      { wait: 1500 },
      { scroll: { to: 200, ms: 0 } },
      'mark',
      { wait: 1200 },
      { click: 'Dlaczego ten projekt się opóźnił?' },
      { wait: 1500 },
      { until: { text: 'Zapisz jako rekord' }, cap: 90_000, record: false },
      { wait: 1000 },
      { scroll: { to: 520, ms: 1500 } },
      { wait: 4000 },
    ],
  },
  {
    id: 'export',
    kind: 'video',
    steps: [
      { goto: '/projekty/RM-2026-003' },
      { wait: 1500 },
      'mark',
      { wait: 1000 },
      { click: { role: 'button', name: 'Eksportuj rekord' } },
      { wait: 2500 },
      { hover: { role: 'menuitem', name: 'PDF' }, ms: 1500 },
    ],
  },
  {
    id: 'graf',
    kind: 'video',
    steps: [
      { goto: '/projekty/RM-2026-003/graf' },
      { wait: 2500 },
      'mark',
      { wait: 1800 },
      { click: { role: 'button', name: 'R04' } },
      { wait: 3000 },
      { click: { role: 'button', name: 'R01' } },
      { wait: 3000 },
    ],
  },
  {
    // The organizer protokół (a copy with one byte appended) was uploaded to RM-2026-002 by the first take
    // (document 33499); this shot opens that processed document instead of uploading again.
    id: 'docs',
    kind: 'video',
    steps: [
      { goto: '/projekty/RM-2026-002/dokumenty' },
      { wait: 1500 },
      'mark',
      { wait: 800 },
      { click: 'Pokaż wszystkie (24)' },
      { wait: 500 },
      { scroll: { to: 'protokol_koniecznosci_zagrodno_kopia.pdf', ms: 1600, offset: -420 } },
      { click: 'protokol_koniecznosci_zagrodno_kopia.pdf' },
      { until: { text: 'Dokument przetworzony' }, cap: 30_000, record: true },
      { scroll: { to: { css: '[aria-label="Analiza dokumentu"]' }, ms: 1400, offset: -90 } },
      { wait: 2800 },
      { scroll: { to: { css: '#co-sie-zmienilo' }, ms: 1800, offset: -110 } },
      { wait: 4500 },
    ],
  },
  {
    id: 'monitoring',
    kind: 'video',
    steps: [
      { goto: '/monitoring' },
      { wait: 3000 },
      'mark',
      { wait: 2200 },
      { click: { role: 'link', name: 'małopolskie' } },
      { wait: 3000 },
      { click: { role: 'link', name: 'powiat nowotarski' } },
      { wait: 3000 },
      { click: { css: 'main a[href*="/umowa/"]' } },
      { wait: 3500 },
    ],
  },
  {
    id: 'przeglad',
    kind: 'video',
    writes: true,
    steps: [{ goto: '/przeglad' }, { wait: 2500 }, 'mark', { wait: 2000 }, { scroll: { to: 260, ms: 1500 } }, { wait: 2500 }, { click: { role: 'button', name: 'Zapisz i dalej' } }, { wait: 2500 }],
  },
  {
    id: 'katalog',
    kind: 'video',
    steps: [{ goto: '/katalog' }, { wait: 2000 }, 'mark', { wait: 1500 }, { scroll: { to: 600, ms: 3500 } }, { wait: 1000 }],
  },
  {
    id: 'zapytaj',
    kind: 'video',
    steps: [
      { goto: '/zapytaj' },
      { wait: 1500 },
      'mark',
      { wait: 1200 },
      { click: 'Zaprojektuj i wybuduj a samo wykonanie' },
      { until: { text: 'dane z bazy umów' }, cap: 60_000, record: false },
      { wait: 1500 },
      { until: { text: 'Zapisz jako rekord' }, cap: 90_000, record: false },
      { scroll: { to: 300, ms: 1500 } },
      { wait: 4500 },
    ],
  },
];
