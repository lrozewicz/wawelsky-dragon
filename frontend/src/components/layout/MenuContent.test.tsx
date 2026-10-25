import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { FeatureFlags } from '../../lib/featureFlags'
import { renderWithProviders } from '../../test/renderWithProviders'

import { MenuContent } from './MenuContent'

const HIDDEN: FeatureFlags = { agent: false, memory: false, search: true, files: true }
const ROUTES = [
  '/datasets',
  '/chats',
  '/searches',
  '/agents',
  '/memories',
  '/files',
  '/user-setting/model',
  '/admin/users',
]

afterEach(cleanup)

describe('MenuContent', () => {
  it('oznacza aktywną pozycję aria-current i zachowuje kolejność', async () => {
    await renderWithProviders(
      <MenuContent
        pathname="/datasets"
        isSuperuser={false}
        flags={HIDDEN}
        mini={false}
        docsUrl=""
      />,
      { route: '/datasets', routes: ROUTES },
    )

    const nav = screen.getByRole('navigation', { name: 'Nawigacja główna' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual([
      'Start',
      'Bazy wiedzy',
      'Czat',
      'Wyszukiwanie',
      'Pliki',
      'Ustawienia',
    ])

    expect(within(nav).getByRole('link', { name: 'Bazy wiedzy' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(within(nav).getByRole('link', { name: 'Start' })).not.toHaveAttribute('aria-current')
  })

  it('ukrywa agenta bez flagi i pokazuje z flagą', async () => {
    const { unmount } = await renderWithProviders(
      <MenuContent pathname="/" isSuperuser={false} flags={HIDDEN} mini={false} docsUrl="" />,
      { routes: ROUTES },
    )
    expect(screen.queryByRole('link', { name: 'Agent' })).not.toBeInTheDocument()
    unmount()

    await renderWithProviders(
      <MenuContent
        pathname="/"
        isSuperuser={false}
        flags={{ ...HIDDEN, agent: true }}
        mini={false}
        docsUrl=""
      />,
      { routes: ROUTES },
    )
    expect(screen.getByRole('link', { name: 'Agent' })).toBeInTheDocument()
  })

  it('pokazuje administrację tylko superuserowi', async () => {
    const { unmount } = await renderWithProviders(
      <MenuContent pathname="/" isSuperuser={false} flags={HIDDEN} mini={false} docsUrl="" />,
      { routes: ROUTES },
    )
    expect(screen.queryByRole('link', { name: 'Administracja' })).not.toBeInTheDocument()
    unmount()

    await renderWithProviders(
      <MenuContent pathname="/" isSuperuser flags={HIDDEN} mini={false} docsUrl="" />,
      { routes: ROUTES },
    )
    expect(screen.getByRole('link', { name: 'Administracja' })).toBeInTheDocument()
  })

  it('renderuje link Pomoc tylko gdy docsUrl podane', async () => {
    const { unmount } = await renderWithProviders(
      <MenuContent pathname="/" isSuperuser={false} flags={HIDDEN} mini={false} docsUrl="" />,
      { routes: ROUTES },
    )
    expect(screen.queryByRole('link', { name: 'Pomoc' })).not.toBeInTheDocument()
    unmount()

    await renderWithProviders(
      <MenuContent
        pathname="/"
        isSuperuser={false}
        flags={HIDDEN}
        mini={false}
        docsUrl="https://d"
      />,
      { routes: ROUTES },
    )
    const help = screen.getByRole('link', { name: 'Pomoc' })
    expect(help).toHaveAttribute('href', 'https://d')
    expect(help).toHaveAttribute('target', '_blank')
  })

  it('w trybie mini udostępnia etykietę przez aria-label, bez widocznego tekstu', async () => {
    await renderWithProviders(
      <MenuContent pathname="/chats" isSuperuser={false} flags={HIDDEN} mini docsUrl="" />,
      { route: '/chats', routes: ROUTES },
    )

    expect(screen.getByRole('link', { name: 'Czat' })).toBeInTheDocument()
    expect(screen.queryByText('Czat')).not.toBeInTheDocument()
  })
})
