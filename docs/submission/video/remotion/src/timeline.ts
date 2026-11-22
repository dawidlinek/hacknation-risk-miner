/**
 * The versions (cuts) of the demo video. Each cut is a LIST of scenes; scenes, captions and
 * transitions are shared, so a new version is a new list, not new code.
 * Every number in a caption comes from src/data.json (live API snapshot) or is read off the
 * capture it sits on. Screen scenes: `from` = seconds into the capture, `dur` = scene length.
 */
import type { Cap } from './components/Caption';
import type { Key } from './components/Screen';
import { FPS } from './clock';
import type { TitleId } from './Cut';
import data from './data.json';

export type Trans = 'fade' | 'slide' | 'wipe' | 'cut';
interface Base {
  dur: number;
  in?: Trans;
}
export type Scene = Base &
  (
    | { kind: 'title'; id: TitleId }
    | { kind: 'logo'; line?: string }
    | { kind: 'chapter'; kicker: string; title: string; sub?: string }
    | { kind: 'question'; q: string; mark?: string; kicker?: string }
    | { kind: 'end'; line?: string }
    | { kind: 'screen'; shot: string; from?: number; rate?: number; cam?: Key[]; caps?: Cap[]; chip?: string; framed?: boolean; url?: string }
  );

export interface Cut {
  id: string;
  title: string;
  angle: string;
  framed?: boolean;
  trans?: Trans;
  scenes: Scene[];
}

const TRANS = 0.5;
export const cutFrames = (cut: Cut): number => {
  let f = 0;
  cut.scenes.forEach((s, i) => {
    f += Math.round(s.dur * FPS);
    if (i > 0 && (s.in ?? cut.trans ?? 'fade') !== 'cut') f -= Math.round(TRANS * FPS);
  });
  return f;
};
export const cutSeconds = (cut: Cut): number => cutFrames(cut) / FPS;

const pl = (n: number) => Math.round(n).toLocaleString('pl-PL').replace(/ /g, ' ');
const LATE = `${Math.round(data.lateShare.value * 100)}%`;
const DB = `${Math.round(data.designBuild.late_share * 100)}%`;
const BO = `${Math.round(data.buildOnly.late_share * 100)}%`;

/* ---------- screen scenes ----------
 * Each capture's camera keys and captions are written in SOURCE seconds (time inside the
 * capture), so one definition serves every version: `shot()` picks a window [from, from+dur],
 * shifts keys and captions into scene time and drops captions outside the window.
 * Source timings come from public/captures/manifest.json (clicks, jumps) and contact sheets. */

interface ShotDef {
  shot: string;
  len: number; // capture length, s (stills: unlimited)
  chip: string;
  url?: string;
  cam: Key[];
  caps: Cap[];
}

function shot(d: ShotDef, dur: number, from = 0, caps?: Cap[]): Scene {
  const f = d.len > 0 ? Math.max(0, Math.min(from, d.len - dur - 0.05)) : 0;
  const cam = d.cam.map((k) => ({ ...k, t: k.t - f }));
  const src = caps ?? d.caps;
  const shifted = caps
    ? caps
    : src
        .map((c) => ({ ...c, from: Math.max(0.3, c.from - f), to: Math.min(dur - 0.15, c.to - f) }))
        .filter((c) => c.to - c.from >= 1.6);
  return { kind: 'screen', shot: d.shot, from: f, dur, cam, caps: shifted, chip: d.chip, ...(d.url ? { url: d.url } : {}) };
}

const NEW: ShotDef = {
  shot: 'new',
  len: 13.3,
  chip: 'Ścieżka b, krok 1 z 5',
  url: '/analizy/nowa',
  cam: [
    { t: 0, s: 1.3, fx: 0.5, fy: 0.3 },
    { t: 4.2, s: 1.3, fx: 0.5, fy: 0.36 },
    { t: 5.2, s: 1.25, fx: 0.5, fy: 0.5 },
    { t: 9.9, s: 1.25, fx: 0.5, fy: 0.62 },
    { t: 10.5, s: 1, fx: 0.5, fy: 0.5 },
    { t: 13.3, s: 1.12, fx: 0.45, fy: 0.35 },
  ],
  caps: [
    { from: 0.4, to: 3.9, text: 'Opisz inwestycję albo dołącz PFU.', kicker: 'Nowa inwestycja', pos: 'bl' },
    { from: 4.5, to: 9.8, text: 'System odczytuje cechy z opisu i PFU, a o brakujące pyta.', pos: 'bl' },
    { from: 10.3, to: 13.2, text: 'Uruchom analizę.', pos: 'br' },
  ],
};

const REPORT: ShotDef = {
  shot: 'report',
  len: 0,
  chip: 'Ścieżka b, krok 2 z 5: raport',
  url: '/analizy/AN-2026-0023',
  cam: [
    { t: 0, s: 1, scroll: 0 },
    { t: 1.8, s: 1.18, fx: 0.5, fy: 0.4, scroll: 120 },
    { t: 5.2, s: 1.3, fx: 0.5, fy: 0.42, scroll: 400 },
    { t: 8.8, s: 1.3, fx: 0.78, fy: 0.45, scroll: 950 },
    { t: 12.5, s: 1.22, fx: 0.38, fy: 0.35, scroll: 950 },
    { t: 20, s: 1.22, fx: 0.38, fy: 0.5, scroll: 1150 },
  ],
  caps: [
    { from: 0.4, to: 4.8, text: 'Grupa porównawcza: 82 podobne umowy z BZP.', kicker: 'Raport', pos: 'br' },
    { from: 5.1, to: 8.5, text: 'Plan 22 mies.: ok. 36% szans na termin. Kilometr droższy niż w 83% umów.', pos: 'br' },
    { from: 8.9, to: 12.2, text: 'Podobne przypadki i cechy, które zdecydowały.', pos: 'bl' },
    { from: 12.5, to: 20, text: 'Na co uważać przed przetargiem: sygnały z PFU, ze stroną.', pos: 'br' },
  ],
};

const REDPEN: ShotDef = {
  shot: 'redpen',
  len: 10.4,
  chip: 'Ścieżka b, krok 3 z 5: Czerwony długopis',
  cam: [
    { t: 0, s: 1.05, fx: 0.5, fy: 0.5 },
    { t: 2.0, s: 1.1, fx: 0.55, fy: 0.5 },
    { t: 2.6, s: 1.45, fx: 0.76, fy: 0.5 },
    { t: 6.4, s: 1.5, fx: 0.76, fy: 0.55 },
    { t: 6.6, s: 1.2, fx: 0.65, fy: 0.5 },
    { t: 10.4, s: 1.35, fx: 0.76, fy: 0.55 },
  ],
  caps: [
    { from: 0.5, to: 2.6, text: 'Czerwony długopis czyta PFU strona po stronie.', kicker: 'Czerwony długopis', pos: 'bl' },
    { from: 2.8, to: 6.4, text: 'Uwaga wskazuje stronę i cytat oraz proponuje zapis do umowy.', pos: 'bl' },
    { from: 6.7, to: 10.3, text: 'Cytat jest sprawdzany w tekście dokumentu.', pos: 'bl' },
  ],
};

const SIM: ShotDef = {
  shot: 'sim',
  len: 15.2,
  chip: 'Ścieżka b, krok 4 z 5: symulacja',
  cam: [
    { t: 0, s: 1.25, fx: 0.36, fy: 0.55 },
    { t: 1.4, s: 1.25, fx: 0.36, fy: 0.55 },
    { t: 2.6, s: 1.15, fx: 0.32, fy: 0.55 },
    { t: 4.2, s: 1.15, fx: 0.32, fy: 0.55 },
    { t: 5.6, s: 1.35, fx: 0.33, fy: 0.62 },
    { t: 8.0, s: 1.35, fx: 0.33, fy: 0.62 },
    { t: 9.2, s: 1.15, fx: 0.32, fy: 0.55 },
    { t: 10.9, s: 1.15, fx: 0.32, fy: 0.55 },
    { t: 12.3, s: 1.4, fx: 0.33, fy: 0.65 },
    { t: 15.2, s: 1.45, fx: 0.33, fy: 0.66 },
  ],
  caps: [
    { from: 0.5, to: 5.6, text: 'Co jeśli? Zaznacz zmianę przed przetargiem.', kicker: 'Symulacja', pos: 'tr' },
    { from: 5.8, to: 15, text: 'Każda zmiana rysuje własną krzywą: kiedy skończysz.', pos: 'tr' },
  ],
};

const PAKIET: ShotDef = {
  shot: 'pakiet',
  len: 8.2,
  chip: 'Ścieżka b, krok 5 z 5: pakiet',
  cam: [
    { t: 0, s: 1.25, fx: 0.38, fy: 0.42 },
    { t: 2.6, s: 1.3, fx: 0.38, fy: 0.42 },
    { t: 4.0, s: 1.55, fx: 0.82, fy: 0.5 },
    { t: 8.2, s: 1.65, fx: 0.83, fy: 0.55 },
  ],
  caps: [
    { from: 0.4, to: 3.8, text: 'Podział ryzyk: ile wykonawcy doliczą w ofertach.', kicker: 'Podział ryzyk i pakiet', pos: 'bl' },
    { from: 4.1, to: 8.1, text: 'Pakiet do akt: DOCX, PDF, CSV albo JSON.', pos: 'bl' },
  ],
};

const PROJEKTY: ShotDef = {
  shot: 'projekty',
  len: 7.0,
  chip: 'Ścieżka a: projekty',
  cam: [
    { t: 0, s: 1.15, fx: 0.42, fy: 0.42 },
    { t: 4.0, s: 1.25, fx: 0.35, fy: 0.55 },
    { t: 4.6, s: 1.15, fx: 0.4, fy: 0.4 },
    { t: 7, s: 1.25, fx: 0.38, fy: 0.42 },
  ],
  caps: [{ from: 0.4, to: 6.9, text: 'Projekty z zestawu organizatora, powiązane z postępowaniami w BZP.', kicker: 'Projekty', pos: 'br' }],
};

const CARD: ShotDef = {
  shot: 'card',
  len: 0,
  chip: 'Ścieżka a: karta projektu',
  url: '/projekty/RM-2026-003',
  cam: [
    { t: 0, s: 1.35, fx: 0.37, fy: 0.42, scroll: 60 },
    { t: 3.6, s: 1.4, fx: 0.37, fy: 0.55, scroll: 160 },
    { t: 8, s: 1.3, fx: 0.37, fy: 0.5, scroll: 1000 },
    { t: 12, s: 1.3, fx: 0.37, fy: 0.5, scroll: 1150 },
  ],
  caps: [
    { from: 0.4, to: 3.8, text: 'Steklin: 277 dni po terminie, zapłacono o 40,3% więcej.', kicker: 'Karta projektu', pos: 'br' },
    { from: 4.1, to: 12, text: 'Przebieg z ogłoszeń BZP: umowa, dopłaty, podstawa art. 455.', pos: 'br' },
  ],
};

const CHAT: ShotDef = {
  shot: 'chat',
  len: 10.2,
  chip: 'Ścieżka a: zapytaj o projekt',
  cam: [
    { t: 0, s: 1.4, fx: 0.33, fy: 0.45 },
    { t: 3.6, s: 1.4, fx: 0.33, fy: 0.5 },
    { t: 10.2, s: 1.45, fx: 0.33, fy: 0.6 },
  ],
  caps: [{ from: 0.4, to: 10, text: 'Pytanie o projekt: odpowiedź podaje źródło i pole ogłoszenia.', kicker: 'Czat na karcie', pos: 'br' }],
};

const EXPORT: ShotDef = {
  shot: 'export',
  len: 6.6,
  chip: 'Ścieżka a: eksport rekordu',
  cam: [{ t: 0, s: 1.2, fx: 0.7, fy: 0.3 }, { t: 2.0, s: 1.7, fx: 0.85, fy: 0.3 }, { t: 6.6, s: 1.8, fx: 0.86, fy: 0.32 }],
  caps: [{ from: 0.4, to: 6.5, text: 'Eksportuj rekord: PDF, DOCX, Markdown, JSON.', pos: 'bl' }],
};

const GRAF: ShotDef = {
  shot: 'graf',
  len: 9.7,
  chip: 'Ścieżka a: graf powiązań',
  cam: [{ t: 0, s: 1.15, fx: 0.42, fy: 0.55 }, { t: 2.6, s: 1.25, fx: 0.5, fy: 0.6 }, { t: 9.7, s: 1.3, fx: 0.55, fy: 0.6 }],
  caps: [
    { from: 0.4, to: 4.6, text: 'Graf: źródło, fakt, wniosek.', kicker: 'Graf powiązań', pos: 'tr' },
    { from: 4.8, to: 9.6, text: 'Kliknięty wniosek pokazuje swoją drogę do ogłoszenia.', pos: 'tr' },
  ],
};

const DOCS: ShotDef = {
  shot: 'docs',
  len: 15.3,
  chip: 'Ścieżka a: dokumenty',
  cam: [
    { t: 0, s: 1.15, fx: 0.42, fy: 0.45 },
    { t: 5.2, s: 1.2, fx: 0.5, fy: 0.5 },
    { t: 6.4, s: 1.75, fx: 0.81, fy: 0.5 },
    { t: 10.6, s: 1.8, fx: 0.82, fy: 0.55 },
    { t: 11.6, s: 1.9, fx: 0.83, fy: 0.5 },
    { t: 15.3, s: 1.95, fx: 0.83, fy: 0.55 },
  ],
  caps: [
    { from: 0.4, to: 6.2, text: 'Dokument z budowy: protokół konieczności aneksowania.', kicker: 'Dokumenty projektu', pos: 'bl' },
    { from: 6.4, to: 10.8, text: 'Agent czyta go etapami: OCR, fakty z cytatem, powiązanie z umową.', pos: 'bl' },
    { from: 11.0, to: 15.2, text: 'Co się zmieniło: termin umowy przesunięty o miesiąc.', pos: 'bl' },
  ],
};

const MONITORING: ShotDef = {
  shot: 'monitoring',
  len: 14.6,
  chip: 'Monitoring',
  cam: [
    { t: 0, s: 1.05, fx: 0.55, fy: 0.5 },
    { t: 2.6, s: 1.05, fx: 0.55, fy: 0.5 },
    { t: 3.4, s: 1.0 },
    { t: 14.6, s: 1.08, fx: 0.4, fy: 0.5 },
  ],
  caps: [
    { from: 0.4, to: 2.9, text: `${LATE} wykonanych umów po terminie, kolor według województw.`, kicker: 'Monitoring', pos: 'bl' },
    { from: 3.2, to: 10.6, text: 'Województwo, powiat, gmina: sygnały w umowach w toku.', pos: 'bl' },
    { from: 10.9, to: 14.5, text: 'Ta umowa jest 1 872 dni po terminie, bez ogłoszenia o wykonaniu.', pos: 'bl' },
  ],
};

const PRZEGLAD: ShotDef = {
  shot: 'przeglad',
  len: 9.5,
  chip: 'Przegląd eksperta',
  cam: [{ t: 0, s: 1.2, fx: 0.38, fy: 0.42 }, { t: 3.8, s: 1.3, fx: 0.38, fy: 0.62 }, { t: 9.5, s: 1.35, fx: 0.38, fy: 0.72 }],
  caps: [
    { from: 0.4, to: 4.6, text: 'Model proponuje przyczynę z cytatem z ogłoszenia.', kicker: 'Przegląd', pos: 'br' },
    { from: 4.8, to: 9.4, text: 'Ekspert zatwierdza albo poprawia. Każdą decyzję można cofnąć.', pos: 'br' },
  ],
};

const KATALOG: ShotDef = {
  shot: 'katalog',
  len: 6,
  chip: 'Katalog wiedzy',
  cam: [{ t: 0, s: 1.15, fx: 0.42, fy: 0.42 }, { t: 6, s: 1.2, fx: 0.42, fy: 0.5 }],
  caps: [{ from: 0.4, to: 5.9, text: 'Katalog ryzyk R01 do R15 z wersjami i propozycjami modelu.', kicker: 'Katalog', pos: 'br' }],
};

const ZAPYTAJ: ShotDef = {
  shot: 'zapytaj',
  len: 9.7,
  chip: 'Zapytaj',
  cam: [{ t: 0, s: 1.35, fx: 0.33, fy: 0.35 }, { t: 3.6, s: 1.4, fx: 0.33, fy: 0.55 }, { t: 9.7, s: 1.45, fx: 0.33, fy: 0.62 }],
  caps: [{ from: 0.4, to: 9.6, text: `Agent pokazuje kroki: zaprojektuj i wybuduj ${DB} po terminie, samo wykonanie ${BO}.`, kicker: 'Zapytaj pamięć', pos: 'br' }],
};

const sNew = (dur = 12.9, caps?: Cap[], from = 0.4) => shot(NEW, dur, from, caps);
const sReport = (dur = 13, caps?: Cap[]) => shot(REPORT, dur, 0, caps);
const sRedpen = (dur = 5.8, from = 0.6, caps?: Cap[]) => shot(REDPEN, dur, from, caps);
const sSim = (dur = 9, from = 0.8, caps?: Cap[]) => shot(SIM, dur, from, caps);
const sPakiet = (dur = 7.5, from = 0.5, caps?: Cap[]) => shot(PAKIET, dur, from, caps);
const sProjekty = (dur = 6, from = 1.0) => shot(PROJEKTY, dur, from);
const sCard = (dur = 8) => shot(CARD, dur, 0);
const sChat = (dur = 8, from = 0.8) => shot(CHAT, dur, from);
const sExport = (dur = 5, from = 0.6) => shot(EXPORT, dur, from);
const sGraf = (dur = 8, from = 1.0) => shot(GRAF, dur, from);
const sDocs = (dur = 9, from = 5.2, caps?: Cap[]) => shot(DOCS, dur, from, caps);
const sMonitoring = (dur = 12, from = 0.8, caps?: Cap[]) => shot(MONITORING, dur, from, caps);
const sPrzeglad = (dur = 6, from?: number) => shot(PRZEGLAD, dur, from ?? Math.max(0, 9.4 - dur));
const sKatalog = (dur = 4.5, from = 0.5) => shot(KATALOG, dur, from);
const sZapytaj = (dur = 8, from = 0.8) => shot(ZAPYTAJ, dur, from);

/* ---------- the versions ---------- */

const chapterB: Scene = { kind: 'chapter', kicker: 'Ścieżka b', title: 'Nowa inwestycja', sub: 'Od opisu i PFU do pakietu do akt.', dur: 2.4, in: 'wipe' };
const chapterA: Scene = { kind: 'chapter', kicker: 'Ścieżka a', title: 'Projekt z pamięci', sub: 'Od rekordu do dowodu w źródle.', dur: 2.4, in: 'wipe' };

export const CUTS: Cut[] = [
  {
    id: 'A',
    title: 'Problem, potem obie ścieżki',
    angle: 'problem-first pitch: live numbers, the scattered sources, then path (b) and path (a)',
    framed: true,
    scenes: [
      { kind: 'title', id: 'hookCompleted', dur: 3.4, in: 'cut' },
      { kind: 'title', id: 'hookLate', dur: 3.2 },
      { kind: 'title', id: 'hookMoney', dur: 3.4 },
      { kind: 'title', id: 'problem', dur: 4.4 },
      { kind: 'logo', dur: 3.0 },
      chapterB,
      sNew(12.9),
      sReport(12.5),
      sRedpen(5.8),
      sSim(8, 7.2),
      sPakiet(7.5),
      chapterA,
      sProjekty(5.5),
      sCard(7),
      sGraf(7.5),
      sDocs(9),
      sMonitoring(11),
      sPrzeglad(6),
      sZapytaj(6.5),
      { kind: 'end', dur: 4.2 },
    ],
  },
  {
    id: 'B',
    title: 'Przejście przez aplikację',
    angle: 'pure walkthrough: path (b) end to end with time to read, then a quick path (a)',
    framed: false,
    scenes: [
      { kind: 'logo', dur: 2.6, in: 'cut', line: 'Ryzyka inwestycji wod-kan z pamięci tysięcy umów.' },
      { ...chapterB, sub: 'Pięć kroków od PFU do pakietu do akt.', dur: 2.3 },
      sNew(12.9),
      sReport(13),
      sRedpen(5.8),
      sSim(9, 6.0),
      sPakiet(7.7),
      { ...chapterA, sub: 'Karta, graf, dokumenty, monitoring, przegląd.', dur: 2.3 },
      sProjekty(5.8),
      sCard(7),
      sChat(6),
      sExport(4.5, 1.2),
      sGraf(8),
      sDocs(9),
      sMonitoring(10.5),
      sPrzeglad(6.5),
      sKatalog(3.5),
      sZapytaj(7),
      { kind: 'end', dur: 3.6 },
    ],
  },
  {
    id: 'C',
    title: 'Zwiastun',
    angle: '60 to 75 s teaser: four live numbers, the logo, the strongest screens, the URL',
    framed: true,
    scenes: [
      { kind: 'title', id: 'hookAll', dur: 4.8, in: 'cut' },
      { kind: 'logo', dur: 2.6 },
      sNew(9, undefined, 4.2),
      sReport(9),
      sRedpen(5.5, 0.9),
      sSim(6, 9.0),
      sPakiet(4.5, 3.6),
      sDocs(6, 9.2),
      sMonitoring(8.5),
      sGraf(5),
      sPrzeglad(5),
      { kind: 'end', dur: 4 },
    ],
  },
  {
    id: 'D',
    title: 'Pytania zamawiającego',
    angle: 'question-led: the questions a municipality asks before a tender, each answered by a screen',
    framed: true,
    scenes: [
      { kind: 'question', kicker: 'Gmina planuje kanalizację', q: 'Czy zdążymy w terminie?', mark: 'w terminie', dur: 2.6, in: 'cut' },
      { kind: 'title', id: 'hookLateSolo', dur: 3.0 },
      { kind: 'logo', dur: 2.8, line: 'Odpowiedzi z tysięcy wykonanych umów.' },
      { kind: 'question', kicker: 'Pytanie 1', q: 'Co wiemy z opisu i PFU?', mark: 'PFU', dur: 2.2, in: 'slide' },
      sNew(12.9),
      { kind: 'question', kicker: 'Pytanie 2', q: 'Zdążymy i starczy pieniędzy?', mark: 'starczy pieniędzy', dur: 2.2, in: 'slide' },
      sReport(12.5),
      { kind: 'question', kicker: 'Pytanie 3', q: 'Co w PFU jest ryzykowne?', mark: 'ryzykowne', dur: 2.2, in: 'slide' },
      sRedpen(5.8),
      { kind: 'question', kicker: 'Pytanie 4', q: 'Co zmienić przed przetargiem?', mark: 'przed przetargiem', dur: 2.2, in: 'slide' },
      sSim(8, 7.2),
      sPakiet(6, 2.0),
      { kind: 'question', kicker: 'Pytanie 5', q: 'Skąd to wiadomo?', mark: 'Skąd', dur: 2.0, in: 'slide' },
      sCard(6),
      sGraf(6),
      sDocs(7, 8.2),
      sPrzeglad(5.5),
      { kind: 'question', kicker: 'Pytanie 6', q: 'Co dzieje się teraz w regionie?', mark: 'teraz', dur: 2.0, in: 'slide' },
      sMonitoring(11),
      { kind: 'end', dur: 4 },
    ],
  },
];

export const NUMBERS_NOTE = `${pl(data.completed.value)} / ${LATE}`;
