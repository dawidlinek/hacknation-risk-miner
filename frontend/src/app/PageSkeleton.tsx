import { SkeletonBlock } from '@/components/common/DataState'
import { Page } from './Page'

/** Shown while a route loader runs (after 150 ms): header line, a summary block and two columns, in the shape of the final layout. */
export function PageSkeleton() {
  return (
    <Page aria-busy="true" aria-label="Wczytywanie strony">
      <SkeletonBlock className="h-11 w-72 rounded-item" />
      <SkeletonBlock className="h-28" />
      <div className="flex flex-wrap gap-9">
        <SkeletonBlock className="h-72 min-w-0 flex-[999_1_560px]" />
        <SkeletonBlock className="h-72 min-w-0 flex-[1_1_360px]" />
      </div>
    </Page>
  )
}
