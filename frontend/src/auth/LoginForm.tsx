import { useQuery } from '@tanstack/react-query'
import { useNavigate, useRouter } from '@tanstack/react-router'
import { useId, useState } from 'react'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { brand } from '@/config/brand'
import { demoPersonasQuery, useDemoLogin, useLogin } from './session'

/** Only same-origin app paths are accepted as a redirect target. */
export function safeRedirect(r: string | undefined): string {
  if (!r || !r.startsWith('/') || r.startsWith('//') || r.startsWith('/zaloguj')) return '/'
  return r
}

export function LoginForm({ redirectTo }: { redirectTo?: string }) {
  const login = useLogin()
  const navigate = useNavigate()
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const uid = useId()
  const personas = useQuery(demoPersonasQuery)
  const demo = useDemoLogin()
  const enter = async () => {
    await router.invalidate()
    navigate({ to: safeRedirect(redirectTo) as never, replace: true })
  }
  const demoOn = Boolean(personas.data && personas.data.length > 0)
  const bad =
    login.error instanceof ApiError &&
    (login.error.status === 401 || login.error.status === 403 || login.error.status === 422)
  return (
    <div className="w-full max-w-[420px] rounded-panel border border-border p-7 shadow-composer">
      <h1 className="t-h2 m-0" data-page-title tabIndex={-1}>
        Zaloguj się
      </h1>
      <p className="mt-1 mb-5 text-[14px] text-text-body-muted">{brand.descriptor}</p>
      {demoOn ? (
        <div className="flex flex-col gap-4">
          {demo.isError ? (
            <p role="alert" className="m-0 text-[14px] text-attention-text">
              Nie udało się zalogować. Spróbuj ponownie.
            </p>
          ) : null}
          <Button
            type="button"
            size="lg"
            disabled={demo.isPending}
            onClick={() => demo.mutate(undefined, { onSuccess: enter })}
          >
            {demo.isPending ? 'Logowanie…' : 'Zaloguj się'}
          </Button>
        </div>
      ) : personas.isLoading ? null : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            login.mutate(
              { username: username.trim(), password },
              {
                onSuccess: async () => {
                  await router.invalidate()
                  navigate({ to: safeRedirect(redirectTo) as never, replace: true })
                },
              },
            )
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${uid}-u`}>Login</Label>
            <Input
              id={`${uid}-u`}
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${uid}-p`}>Hasło</Label>
            <Input
              id={`${uid}-p`}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {login.isError ? (
            <p role="alert" className="m-0 text-[14px] text-attention-text">
              {bad ? 'Nieprawidłowy login lub hasło.' : 'Nie udało się zalogować. Spróbuj ponownie.'}
            </p>
          ) : null}
          <Button type="submit" size="lg" disabled={login.isPending}>
            {login.isPending ? 'Logowanie…' : 'Zaloguj się'}
          </Button>
        </form>
      )}
    </div>
  )
}
