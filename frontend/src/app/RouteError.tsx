import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { type ErrorComponentProps, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Page } from './Page'

export function ErrorBox({ error, onRetry, title = 'Nie udało się wczytać danych.' }: { error: unknown; onRetry?: () => void; title?: string }) {
  const reqId = error instanceof ApiError ? error.requestId : null
  const detail = error instanceof ApiError ? error.detail : null
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-panel bg-soft p-6">
      <p className="t-h3 m-0">{title}</p>
      {detail ? <p className="m-0 text-text-body-muted">{detail}</p> : null}
      {onRetry ? (
        <Button variant="outline" onClick={onRetry}>
          Spróbuj ponownie
        </Button>
      ) : null}
      {reqId ? <span className="t-mono text-muted">identyfikator żądania: {reqId}</span> : null}
    </div>
  )
}

export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const qr = useQueryErrorResetBoundary()
  useEffect(() => qr.reset(), [qr])
  return (
    <Page>
      <ErrorBox
        error={error}
        onRetry={() => {
          reset()
          router.invalidate()
        }}
      />
    </Page>
  )
}
