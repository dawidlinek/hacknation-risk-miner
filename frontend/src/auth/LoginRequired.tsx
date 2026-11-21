import { useNavigate, useRouterState } from '@tanstack/react-router'
import { cloneElement, isValidElement, type MouseEvent, type ReactElement } from 'react'
import { useSession } from './session'

/**
 * Wraps an action that needs login ("Obserwuj", "Zgłoś jako przypadek", "Dodaj dokument", "Wzbogać ponownie").
 * Public click → /zaloguj?redirect=<current href>; logged in → the child's own onClick.
 */
export function LoginRequired({
  children,
}: {
  children: ReactElement<{ onClick?: (e: MouseEvent) => void }>
}) {
  const { isPublic } = useSession()
  const navigate = useNavigate()
  const href = useRouterState({ select: (s) => s.location.href })
  if (!isPublic || !isValidElement(children)) return children
  return cloneElement(children, {
    onClick: (e: MouseEvent) => {
      e.preventDefault()
      navigate({ to: '/zaloguj', search: { redirect: href } })
    },
  })
}
