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
  const bad =
    login.error instanceof ApiError &&
    (login.error.status === 401 || login.error.status === 403 || login.error.status === 422)
  return (
    <div className="w-full max-w-[420px] rounded-panel border border-border p-7 shadow-composer">
      <h1 className="t-h2 m-0" data-page-title tabIndex={-1}>
        Zaloguj się
      </h1>
      <p className="mt-1 mb-5 text-[14px] text-text-body-muted">{brand.descriptor}</p>
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
      {personas.data && personas.data.length > 0 ? (
        <section
          aria-labelledby={`${uid}-demo`}
          className="mt-6 flex flex-col gap-2 border-t border-divider pt-5"
        >
          <h2 id={`${uid}-demo`} className="t-item m-0">
            Wejdź jednym kliknięciem
          </h2>
          <p className="m-0 text-[13px] text-text-body-muted">Konta demonstracyjne, bez hasła.</p>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {personas.data.map((p) => (
              <li key={p.persona}>
                <button
                  type="button"
                  disabled={demo.isPending}
                  onClick={() => demo.mutate(p.persona, { onSuccess: enter })}
                  className="flex w-full flex-col items-start gap-0.5 rounded-item border border-border bg-surface px-4 py-3 text-left hover:bg-soft disabled:opacity-60"
                >
                  <span className="t-item flex items-center gap-2">
                    {p.label}
                    {p.read_only ? (
                      <span className="t-mono rounded-pill bg-soft-2 px-2 py-0.5 text-muted">
                        tylko do odczytu
                      </span>
                    ) : null}
                  </span>
                  <span className="text-[13px] text-text-body-muted">{p.description}</span>
                </button>
              </li>
            ))}
          </ul>
          {demo.isError ? (
            <p role="alert" className="m-0 text-[14px] text-attention-text">
              Nie udało się zalogować. Spróbuj ponownie.
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
