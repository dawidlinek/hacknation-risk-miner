import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { type ErrorComponentProps, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'
import { ErrorBox } from '@/app/RouteError'
import { SkeletonBlock, SkeletonLines } from '@/components/common/DataState'
import { SummaryCardSkeleton } from '@/components/common/SummaryCard'

/** Route pending states in the shape of the final layout (never a lone spinner). */

export function ReportSkeleton() {
  return (
    <div className="flex flex-col gap-7" role="status" aria-busy="true" aria-label="Wczytujemy raport">
      <SkeletonBlock className="h-10 w-2/3" />
      <SummaryCardSkeleton note="Liczymy: grupa porównawcza, podobne przypadki, zapisy w dokumentach…" />
      <div className="grid gap-3 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} className="h-40" />
        ))}
      </div>
      <div className="flex flex-wrap gap-9">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-3">
          <SkeletonLines lines={5} />
        </div>
        <div className="flex min-w-0 flex-[1_1_360px] flex-col gap-3">
          <SkeletonBlock className="h-64" />
        </div>
      </div>
    </div>
  )
}

export function SimulationSkeleton() {
  return (
    <div className="flex flex-col gap-7" role="status" aria-busy="true" aria-label="Wczytujemy symulację">
      <SkeletonBlock className="h-10 w-1/2" />
      <SummaryCardSkeleton note="Losujemy podobne umowy…" />
      <SkeletonBlock className="h-[320px]" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-20" />
        ))}
      </div>
    </div>
  )
}

export function AllocationSkeleton() {
  return (
    <div className="flex flex-col gap-7" role="status" aria-busy="true" aria-label="Wczytujemy podział ryzyk">
      <SkeletonBlock className="h-10 w-1/2" />
      <SkeletonBlock className="h-36" />
      {[0, 1, 2, 3, 4].map((i) => (
        <SkeletonBlock key={i} className="h-16" />
      ))}
    </div>
  )
}

export function RedPenSkeleton() {
  return (
    <div
      className="flex flex-wrap items-start gap-9"
      role="status"
      aria-busy="true"
      aria-label="Wczytujemy dokument"
    >
      <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-3">
        <SkeletonBlock className="h-11" />
        <SkeletonBlock className="h-[480px]" />
      </div>
      <div className="flex min-w-0 flex-[1_1_360px] flex-col gap-3">
        <SkeletonLines lines={2} />
        {[0, 1, 2].map((i) => (
          <SkeletonBlock key={i} className="h-24" />
        ))}
      </div>
    </div>
  )
}

/** Route error inside the analysis layout (the app's RouteError adds its own page frame). */
export function SectionError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const qr = useQueryErrorResetBoundary()
  useEffect(() => qr.reset(), [qr])
  return (
    <ErrorBox
      error={error}
      onRetry={() => {
        reset()
        router.invalidate()
      }}
    />
  )
}
