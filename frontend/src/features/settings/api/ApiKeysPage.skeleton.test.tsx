/**
 * Strona kluczy API w stanie ładowania (QA V12-z-2b MINOR-2): dopóki chunk `KeysGrid` się
 * ładuje, w miejscu siatki jest szkielet wierszy (`GridSkeleton`), nie goły szary prostokąt.
 * Odrębny plik, bo `vi.mock` zatrzymuje moduł dla CAŁEGO pliku — pozostałe testy strony
 * (`ApiKeysPage.test.tsx`) potrzebują prawdziwej siatki.
 */
import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { settingsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

// Import `./KeysGrid` nigdy się nie kończy — `lazy` zostaje w stanie ładowania i strona
// pokazuje fallback `Suspense`, jak przy wolnym łączeniu.
vi.mock('./KeysGrid', () => new Promise(() => {}))

import { ApiKeysPage } from './ApiKeysPage'

afterEach(() => {
  cleanup()
  server.resetHandlers()
})

describe('ApiKeysPage — stan ładowania siatki', () => {
  it('pokazuje szkielet wierszy, dopóki chunk siatki się ładuje', async () => {
    server.use(...settingsHandlers({}))
    renderWithProviders(<ApiKeysPage />)

    const skeleton = await screen.findByTestId('keys-grid-skeleton')
    expect(skeleton.querySelectorAll('.MuiSkeleton-root').length).toBeGreaterThan(2)
    // Goły prostokąt (jeden `Skeleton` na całą siatkę) przestał być fallbackiem — szkielet
    // ma wiersze, a karta serwera API renderuje się obok.
    expect(screen.getByRole('heading', { name: 'API serwera' })).toBeInTheDocument()
  })
})
