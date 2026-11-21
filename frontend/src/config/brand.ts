// The only place the product name exists (design/README.md §1).
export const brand = {
  name: 'ex ante',
  wordA: 'ex',
  wordB: 'ante',
  tagline: 'Wiedza ex post, decyzje ex ante.',
  descriptor: 'Risk Miner dla inwestycji publicznych',
} as const

export const pageTitle = (page?: string) => (page ? `${page} | ${brand.name}` : brand.name)
