const rules = new Intl.PluralRules('pl-PL')

/** plural(5, ['umowa', 'umowy', 'umów']) → 'umów' */
export function plural(n: number, forms: [one: string, few: string, many: string]): string {
  if (!Number.isInteger(n)) return forms[1]
  const cat = rules.select(n)
  if (cat === 'one') return forms[0]
  if (cat === 'few') return forms[1]
  return forms[2]
}

export const W = {
  umowa: ['umowa', 'umowy', 'umów'],
  sygnal: ['sygnał', 'sygnały', 'sygnałów'],
  ryzyko: ['ryzyko', 'ryzyka', 'ryzyk'],
  dzien: ['dzień', 'dni', 'dni'],
  uwaga: ['uwaga', 'uwagi', 'uwag'],
  brak: ['brak', 'braki', 'braków'],
  projekt: ['projekt', 'projekty', 'projektów'],
  wniosek: ['wniosek', 'wnioski', 'wniosków'],
  czeka: ['czeka', 'czekają', 'czeka'],
  strona: ['strona', 'strony', 'stron'],
} satisfies Record<string, [string, string, string]>

/** `pl(3, W.ryzyko)` → '3 ryzyka' (NBSP) */
export const pl = (n: number, forms: [string, string, string]) => `${n} ${plural(n, forms)}`
