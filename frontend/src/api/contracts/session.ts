export type Role = 'public' | 'expert' | 'admin'
export interface Session {
  role: Role
  name: string | null
  initials: string | null
  /** "demo" when logged in with the one-click login */
  persona?: string | null
  /** legacy flag, the backend now always sends false (one demo user with full rights) */
  read_only?: boolean
}
export interface DemoPersona {
  persona: string
  label: string
  description: string
  role: Role
}
export interface NavCounts {
  review_open: number
  monitoring_new: number
}
export interface LoginIn {
  username: string
  password: string
}
