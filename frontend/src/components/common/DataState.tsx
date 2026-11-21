import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ErrorBox } from '@/app/RouteError'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { fmtN } from '@/lib/format'

/** Inline loading/error/empty for secondary panels (primary data uses route loaders + suspense). */
export function DataState<T>({
  query,
  skeleton,
  empty,
  isEmpty,
  children,
}: {
  query: Pick<UseQueryResult<T>, 'data' | 'isPending' | 'isError' | 'error' | 'refetch'>
  skeleton?: ReactNode
  empty?: ReactNode
  isEmpty?: (d: T) => boolean
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <>{skeleton ?? <SkeletonLines />}</>
  if (query.isError) return <ErrorBox error={query.error} onRetry={() => query.refetch()} />
  const d = query.data as T
  if (empty && isEmpty?.(d)) return <EmptyState>{empty}</EmptyState>
  return <>{children(d)}</>
}

export function SkeletonLines({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-2', className)} aria-busy="true" aria-label="Wczytywanie">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className="h-4 rounded-chip bg-soft-2" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  )
}

export function SkeletonBlock({ className }: { className?: string }) {
  return <Skeleton className={cn('rounded-card bg-soft', className)} />
}

export function EmptyState({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-item bg-soft px-4 py-3 text-[14px] text-text-body-muted', className)}>{children}</div>
}

/** "za mało danych (n = 7)" */
export function Insufficient({ n, className }: { n: number | null | undefined; className?: string }) {
  return (
    <span className={cn('text-text-secondary', className)}>
      za mało danych{n !== null && n !== undefined ? <span className="t-mono text-muted"> ({fmtN(n)})</span> : null}
    </span>
  )
}
