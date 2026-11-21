// Test helpers: the project layout (F2) loads GET /api/projects/{id}/card before any tab renders.
import { HttpResponse, http } from 'msw'

export const cardHandler = (opts: { have?: number; expected?: number } = {}) =>
  http.get('/api/projects/:id/card', ({ params }) =>
    HttpResponse.json({
      id: params.id,
      rm_id: params.id,
      title: 'Oczyszczalnia ścieków w Steklinie',
      auto_card: false,
      buyer: { name: 'Gmina Czernikowo', nip: '8792466869', nip_valid: true },
      summary: {
        sentence: 'Skończono 277 dni po terminie.',
        prov: { role: 'calc', review_status: 'auto', n: 1 },
      },
      doc_counts: { have: opts.have ?? 0, expected: opts.expected ?? 4 },
      plan_vs_actual: [],
      steps: [],
      events: [],
      similar: [],
      gaps: [],
      identifiers: [],
      chat: { suggestions: [] },
    }),
  )
