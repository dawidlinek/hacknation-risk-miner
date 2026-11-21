import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { Page } from '@/app/Page'
import { LoginForm } from '@/auth/LoginForm'
import { pageTitle } from '@/config/brand'

export const Route = createFileRoute('/zaloguj')({
  validateSearch: z.object({ redirect: z.string().optional().catch(undefined) }),
  head: () => ({ meta: [{ title: pageTitle('Zaloguj się') }] }),
  component: LoginPage,
})

function LoginPage() {
  const { redirect } = Route.useSearch()
  return (
    <Page className="items-center">
      <LoginForm redirectTo={redirect} />
    </Page>
  )
}
