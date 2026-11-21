import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderRoute } from '@/test/render'

describe('AppHeader', () => {
  it('public: 4 nav items, Zapytaj, Zaloguj się, no counts', async () => {
    await renderRoute('/zaloguj')
    const nav = await screen.findByRole('navigation', { name: 'Moduły' })
    const links = within(nav)
      .getAllByRole('link')
      .map((a) => a.textContent)
    expect(links).toEqual(['Monitoring', 'Nowa inwestycja', 'Projekty', 'Wnioski'])
    expect(screen.getByRole('link', { name: /Zapytaj/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Zaloguj się' })).toBeInTheDocument()
    expect(screen.queryByText('Więcej')).not.toBeInTheDocument()
  })
  it('expert: 7 items with counts and Więcej', async () => {
    localStorage.setItem('rm.mockRole', 'expert')
    await renderRoute('/zaloguj')
    const nav = await screen.findByRole('navigation', { name: 'Moduły' })
    await within(nav).findByText('37')
    const links = within(nav).getAllByRole('link')
    expect(links.map((a) => a.textContent?.replace(/, czeka: \d+/, '').replace(/\d+$/, ''))).toEqual([
      'Pulpit',
      'Monitoring',
      'Nowa inwestycja',
      'Projekty',
      'Wnioski',
      'Przegląd',
      'Katalog',
    ])
    expect(within(nav).getByText('12')).toBeInTheDocument()
    expect(within(nav).getByRole('button', { name: /Więcej/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /konto/i })).toBeInTheDocument()
  })
})
