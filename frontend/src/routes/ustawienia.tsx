import { createFileRoute, redirect } from '@tanstack/react-router'

// Screen removed from the product (user decision, 21.11.2026): old links go to the start page.
export const Route = createFileRoute('/ustawienia')({
  beforeLoad: () => {
    throw redirect({ to: '/' })
  },
})
