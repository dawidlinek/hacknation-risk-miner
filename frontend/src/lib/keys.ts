// Query keys (frontend.md §1.3). Add new keys here or locally in a feature's api.ts.
export const keys = {
  session: ['session'] as const,
  features: ['config', 'features'] as const,
  navCounts: ['nav', 'counts'] as const,
  dashboard: ['dashboard'] as const,
  askSuggestions: (ctx: string) => ['ask', 'suggestions', ctx] as const,
  questions: ['questions'] as const,
  question: (id: string) => ['questions', id] as const,
  analysis: (id: string) => ['analysis', id] as const,
  analysisDraft: (id: string) => ['analysis', id, 'draft'] as const,
  simulation: (id: string) => ['analysis', id, 'simulation'] as const,
  allocation: (id: string) => ['analysis', id, 'allocation'] as const,
  redpen: (id: string, doc: number | string) => ['analysis', id, 'redpen', String(doc)] as const,
  project: (id: string) => ['project', id] as const,
  projectCard: (id: string) => ['project', id, 'card'] as const,
  monitoringRegions: (level: string, parent: string | null, filters: unknown) => ['monitoring', 'regions', level, parent, filters] as const,
}
