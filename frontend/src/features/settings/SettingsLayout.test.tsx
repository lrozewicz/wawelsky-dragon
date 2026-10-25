import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { SettingsLayout } from './SettingsLayout'
import type { SettingsTabKey } from './SettingsLayout'

afterEach(cleanup)
afterEach(() => vi.unstubAllGlobals())

/** Trasy zakładek rejestrowane w routerze testowym, by `<Link>` z `Tab` działały. */
const ROUTES = ['/user-setting/model', '/user-setting/profile', '/user-setting/api']

async function renderLayout(active: SettingsTabKey = 'model') {
  return renderWithProviders(
    <SettingsLayout active={active}>
      <div>treść zakładki</div>
    </SettingsLayout>,
    { route: '/user-setting/model', routes: ROUTES },
  )
}

describe('SettingsLayout', () => {
  it('pokazuje nagłówek sekcji i treść zakładki', async () => {
    await renderLayout()

    expect(await screen.findByRole('heading', { level: 1, name: 'Ustawienia' })).toBeInTheDocument()
    expect(screen.getByText('treść zakładki')).toBeInTheDocument()
  })

  it('renderuje trzy zakładki-linki w kolejności z kontraktu', async () => {
    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Dostawcy modeli', 'Profil', 'Klucze API'])
    expect(tabs[0]).toHaveAttribute('href', '/user-setting/model')
    expect(tabs[1]).toHaveAttribute('href', '/user-setting/profile')
    expect(tabs[2]).toHaveAttribute('href', '/user-setting/api')
    expect(screen.getByTestId('settings-tab-model')).toBeInTheDocument()
    expect(screen.getByTestId('settings-tab-profile')).toBeInTheDocument()
    expect(screen.getByTestId('settings-tab-api')).toBeInTheDocument()
  })

  it('zaznacza zakładkę wskazaną przez `active`', async () => {
    await renderLayout('profile')
    await screen.findByRole('heading', { level: 1 })

    expect(screen.getByTestId('settings-tab-profile')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('settings-tab-model')).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByTestId('settings-tab-api')).toHaveAttribute('aria-selected', 'false')
  })

  it('poniżej progu md zakładki przewijają się poziomo', async () => {
    stubMatchMedia(true)

    await renderLayout()
    await screen.findByRole('heading', { level: 1 })

    expect(document.querySelector('.MuiTabs-scrollableX')).not.toBeNull()
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
