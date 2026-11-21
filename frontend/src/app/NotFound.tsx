import { Link } from '@tanstack/react-router'
import { Page } from './Page'

export function NotFound({ title = 'Nie ma takiej strony.' }: { title?: string }) {
  return (
    <Page>
      <div className="flex flex-col items-start gap-3 rounded-panel bg-soft p-6">
        <h1 className="t-h2 m-0" data-page-title tabIndex={-1}>
          {title}
        </h1>
        <Link to="/" className="font-medium">
          Wróć na stronę główną
        </Link>
      </div>
    </Page>
  )
}
