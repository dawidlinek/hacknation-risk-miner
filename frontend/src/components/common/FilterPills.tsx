import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface PillOption<V extends string = string> {
  value: V
  label: ReactNode
  /** shown after the label in mono */
  count?: number | null
  hidden?: boolean
}

/** Single-select pill filter (aria-pressed buttons). Extra controls (a dropdown) go in `children`. */
export function FilterPills<V extends string>({
  options,
  value,
  onChange,
  label = 'Filtry',
  className,
  children,
}: {
  options: PillOption<V>[]
  value: V
  onChange: (v: V) => void
  label?: string
  className?: string
  children?: ReactNode
}) {
  return (
    <fieldset className={cn('m-0 flex min-w-0 flex-wrap items-center gap-2 border-0 p-0', className)}>
      <legend className="sr-only">{label}</legend>
      {options
        .filter((o) => !o.hidden)
        .map((o) => {
          const on = o.value === value
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(o.value)}
              className={cn(
                'inline-flex min-h-10 items-center gap-1.5 rounded-pill px-4 text-[14px] font-medium transition-colors',
                on
                  ? 'bg-ink text-on-ink'
                  : 'border border-border bg-surface text-text-secondary hover:bg-soft',
              )}
            >
              {o.label}
              {o.count !== undefined && o.count !== null ? (
                <span className="t-mono opacity-80">{o.count}</span>
              ) : null}
            </button>
          )
        })}
      {children}
    </fieldset>
  )
}
