export type Role = 'public' | 'expert' | 'admin'
export interface Session {
  role: Role
  name: string | null
  initials: string | null
  /** demo persona (juror, expert, admin) when logged in with the one-click login */
  persona?: string | null
  /** read-only account: reads everything, every write answers 403 read_only */
  read_only?: boolean
}
export interface DemoPersona {
  persona: 'juror' | 'expert' | 'admin'
  label: string
  description: string
  role: Role
  read_only: boolean
}
export interface NavCounts {
  review_open: number
  monitoring_new: number
}
export interface LoginIn {
  username: string
  password: string
}
