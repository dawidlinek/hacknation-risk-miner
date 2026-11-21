import type { RequestHandler } from 'msw'

// Every ./<domain>.ts exporting `handlers` is registered automatically: adding a domain never edits this file.
const modules = import.meta.glob<{ handlers?: RequestHandler[] }>(['./*.ts', '!./index.ts'], { eager: true })
export const handlers: RequestHandler[] = Object.values(modules).flatMap((m) => m.handlers ?? [])
