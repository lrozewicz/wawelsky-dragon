import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { AdminLayout } from './AdminLayout'
import type { AdminTabKey } from './AdminLayout'

afterEach(cleanup)
afterEach(() => vi.unstubAllGlobals())

/** Trasy zakładek rejestrowane w routerze testowym, by `<Link>` z `Tab` działały. */
const ROUTES = ['/admin/users', '/admin/access', '/admin/status', '/admin/integrations']

type RenderOptions = {
  active?: AdminTabKey
  showIntegrations?: boolean
}

async function renderLayout(options: RenderOptions = {}) {
  const { active = 'users', showIntegrations } = options

  return renderWithProviders(
    <AdminLayout active={active} showIntegrations={showIntegrations}>
      <div>treść zakładki</div>
    </AdminLayout>,
    { route: '/admin/users', routes: ROUTES },
  )
}

describe('AdminLayout', () => {
  it('pokazuje nagłówek sekcji i treść zakładki', async () => {
    await renderLayout()

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Administracja' }),
    ).toBeInTheDocument()
    expect(screen.getByText('treść zakładki')).toBeInTheDocument()
  })

  it('bez `showIntegrations` renderuje trzy zakładki-linki w kolejności z kontraktu', async () => {
    await renderLayout({ active: 'status' })
    await screen.findByRole('heading', { level: 1 })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Użytkownicy',
      'Dostęp do asystentów',
      'Status systemu',
    ])
    expect(tabs[0]).toHaveAttribute('href', '/admin/users')
    expect(tabs[1]).toHaveAttribute('href', '/admin/access')
    expect(tabs[2]).toHaveAttribute('href', '/admin/status')
    expect(screen.getByTestId('admin-tab-users')).toBeInTheDocument()
    expect(screen.getByTestId('admin-tab-access')).toBeInTheDocument()
    expect(screen.getByTestId('admin-tab-status')).toBeInTheDocument()
    expect(screen.queryByTestId('admin-tab-integrations')).not.toBeInTheDocument()
    expect(screen.queryByText('Integracje')).not.toBeInTheDocument()
  })

  it('z `showIntegrations` dodaje czwartą zakładkę „Integracje” na końcu', async () => {
    await renderLayout({ showIntegrations: true })
    await screen.findByRole('heading', { level: 1 })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Użytkownicy',
      'Dostęp do asystentów',
      'Status systemu',
      'Integracje',
    ])
    expect(screen.getByTestId('admin-tab-integrations')).toHaveAttribute(
      'href',
      '/admin/integrations',
    )
  })

  it('zaznacza zakładkę wskazaną przez `active`', async () => {
    await renderLayout({ active: 'access' })
    await screen.findByRole('heading', { level: 1 })

    expect(screen.getByTestId('admin-tab-access')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('admin-tab-users')).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByTestId('admin-tab-status')).toHaveAttribute('aria-selected', 'false')
  })

  it('poniżej progu md zakładki przewijają się poziomo', async () => {
    stubMatchMedia(true)

    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    expect(document.querySelector('.MuiTabs-scrollableX')).not.toBeNull()
  })

  it('U6 (zmiana SC-E5-H8z-03): poniżej progu md paskowi nie rezerwuje się miejsca na przyciski przewijania', async () => {
    stubMatchMedia(true)

    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    // Zakładki zawijają do rzędów, więc przewijanie (i przyciski — także ich rezerwa ~40 px
    // przed pierwszą zakładką) jest zbędne: MUI ich w ogóle nie renderuje.
    expect(document.querySelector('.MuiTabs-scrollButtons')).toBeNull()
  })
})

/** jsdom nie zna `matchMedia` — atrapa zwraca `true` na każde zapytanie (wąskie okno). */
function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  )
}
