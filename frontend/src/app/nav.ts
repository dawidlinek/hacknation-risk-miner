import type { NavCounts } from '@/api/contracts/session'
import type { FeatureName } from '@/config/features'

export interface NavItem {
  label: string
  to: string
  /** pathname prefixes that make the pill active */
  match: string[]
  exact?: boolean
  flag?: FeatureName
  /** shown only when logged in */
  expertOnly?: boolean
  count?: keyof NavCounts
}

// README §4: public = Monitoring, Nowa inwestycja, Projekty; logged in adds Pulpit, Przegląd, Katalog and counts.
export const NAV: NavItem[] = [
  { label: 'Pulpit', to: '/', match: ['/'], exact: true, expertOnly: true },
  { label: 'Monitoring', to: '/monitoring', match: ['/monitoring'], flag: 'radar', count: 'monitoring_new' },
  { label: 'Nowa inwestycja', to: '/analizy/nowa', match: ['/analizy'] },
  { label: 'Projekty', to: '/projekty', match: ['/projekty'] },
  {
    label: 'Przegląd',
    to: '/przeglad',
    match: ['/przeglad'],
    expertOnly: true,
    flag: 'review_queue',
    count: 'review_open',
  },
  { label: 'Katalog', to: '/katalog', match: ['/katalog'], expertOnly: true },
]

export const MORE: NavItem[] = [
  { label: 'Import i źródła', to: '/zrodla', match: ['/zrodla'], expertOnly: true },
  { label: 'Historia', to: '/historia', match: ['/historia'], expertOnly: true },
  { label: 'Ustawienia', to: '/ustawienia', match: ['/ustawienia'], expertOnly: true, flag: 'settings_view' },
]

export function isActive(item: NavItem, pathname: string) {
  if (item.exact) return pathname === item.to
  return item.match.some((m) => pathname === m || pathname.startsWith(`${m}/`))
}
