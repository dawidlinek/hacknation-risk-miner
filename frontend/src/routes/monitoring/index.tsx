import { createFileRoute } from '@tanstack/react-router'
import { NationalPanel } from '@/features/monitoring/NationalPanel'

export const Route = createFileRoute('/monitoring/')({ component: NationalPanel })
