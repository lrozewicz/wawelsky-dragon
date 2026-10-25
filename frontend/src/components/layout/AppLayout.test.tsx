import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CssBaseline from '@mui/material/CssBaseline'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'

import { resetEnvCache } from '../../app/env'
import { changeLanguage, initI18n } from '../../i18n'
import type { Language } from '../../i18n'
import AppTheme from '../../theme/AppTheme'
import { renderWithProviders } from '../../test/renderWithProviders'

import { AppLayout } from './AppLayout'
import type { AppUser } from './types'

const ROUTES = [
  '/datasets',
  '/chats',
  '/searches',
  '/agents',
  '/memories',
  '/files',
  '/user-setting/model',
  '/user-setting/profile',
  '/admin/users',
]
const USER: AppUser = { name: 'Jan Kowalski', email: 'jan@example.com' }

beforeEach(() => {
  localStorage.clear()
  delete window.__ENV__
  resetEnvCache()
})

afterEach(() => {
  cleanup()
  delete window.__ENV__
  resetEnvCache()
})

type LayoutOverrides = {
  isSuperuser?: boolean
  showModelsAlert?: boolean
  onLogout?: () => void
  onLanguageChange?: (language: Language) => void
}

function renderLayout(overrides: LayoutOverrides = {}) {
  return renderWithProviders(
    <AppLayout
      user={USER}
      isSuperuser={overrides.isSuperuser ?? false}
      showModelsAlert={overrides.showModelsAlert ?? false}
      onLogout={overrides.onLogout ?? vi.fn()}
      onLanguageChange={overrides.onLanguageChange}
    >
      <p>treść</p>
    </AppLayout>,
    { route: '/', routes: ROUTES },
  )
}

// Własny router (poza renderWithProviders) — do sprawdzenia `staticData.fullBleed` na trasie.
async function renderWithRoute(path: string, staticData: { fullBleed?: boolean }) {
  await initI18n('pl')
  const rootRoute = createRootRoute()
  const layoutRoute = createRoute({
    getParentRoute: () => rootRoute,
    path,
    staticData,
    component: () => (
      <AppLayout user={USER} isSuperuser={false} showModelsAlert={false} onLogout={vi.fn()}>
        <p>x</p>
      </AppLayout>
    ),
  })
  const extraRoutes = ROUTES.map((routePath) =>
    createRoute({ getParentRoute: () => rootRoute, path: routePath, component: () => null }),
  )
  const router = createRouter({
    routeTree: rootRoute.addChildren([layoutRoute, ...extraRoutes]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  await router.load()

  await act(async () => {
    render(
      <AppTheme>
        <CssBaseline />
        <RouterProvider router={router} />
      </AppTheme>,
    )
  })
}

describe('AppLayout', () => {
  it('pierwszym elementem fokusowalnym jest link Przejdź do treści', async () => {
    const user = userEvent.setup()
    await renderLayout()

    await user.tab()

    const skipLink = screen.getByRole('link', { name: 'Przejdź do treści' })
    expect(skipLink).toHaveFocus()
    expect(skipLink).toHaveAttribute('href', '#main-content')
  })

  it('renderuje main z id main-content i treścią dziecka', async () => {
    await renderLayout()

    const main = document.getElementById('main-content')
    expect(main).not.toBeNull()
    expect(main?.tagName).toBe('MAIN')
    expect(main).toHaveTextContent('treść')
  })

  it('zawiera nawigację o nazwie Nawigacja główna', async () => {
    await renderLayout()

    const navigations = screen.getAllByRole('navigation')
    expect(navigations.some((nav) => nav.getAttribute('aria-label') === 'Nawigacja główna')).toBe(
      true,
    )
  })

  it('bez showModelsAlert nie pokazuje alertu modeli', async () => {
    await renderLayout()

    expect(screen.queryByText('Skonfiguruj modele')).not.toBeInTheDocument()
  })

  it('pokazuje alert modeli, gdy showModelsAlert', async () => {
    await renderLayout({ showModelsAlert: true })

    expect(screen.getByText('Skonfiguruj modele')).toBeInTheDocument()
  })

  it('pokazuje pozycję Agent przy włączonej fladze', async () => {
    window.__ENV__ = { FEATURE_AGENT: 'true' }
    resetEnvCache()

    await renderLayout()

    expect(screen.getByRole('link', { name: 'Agent' })).toBeInTheDocument()
  })

  it('ukrywa pozycję Agent bez flagi', async () => {
    await renderLayout()

    expect(screen.queryByRole('link', { name: 'Agent' })).not.toBeInTheDocument()
  })

  it('klik Wyloguj w menu użytkownika woła onLogout', async () => {
    const user = userEvent.setup()
    const onLogout = vi.fn()
    await renderLayout({ onLogout })

    await user.click(screen.getByRole('button', { name: 'Menu użytkownika' }))
    await user.click(screen.getByRole('menuitem', { name: 'Wyloguj' }))

    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('zmiana języka woła onLanguageChange zamiast domyślnej funkcji', async () => {
    const user = userEvent.setup()
    const onLanguageChange = vi.fn(async (language: Language) => {
      await changeLanguage(language)
    })
    await renderLayout({ onLanguageChange })
    // Element nawigacji łapiemy przed zmianą języka — po niej zmienia się jego aria-label.
    const nav = screen.getByRole('navigation', { name: 'Nawigacja główna' })

    await user.click(screen.getByRole('button', { name: 'Język' }))
    await user.click(screen.getByRole('menuitem', { name: 'English' }))

    expect(onLanguageChange).toHaveBeenCalledWith('en')
    expect(await within(nav).findByText('Home')).toBeInTheDocument()
  })

  it('bez onLanguageChange zmienia język domyślną funkcją i18n', async () => {
    const user = userEvent.setup()
    await renderLayout()
    const nav = screen.getByRole('navigation', { name: 'Nawigacja główna' })

    await user.click(screen.getByRole('button', { name: 'Język' }))
    await user.click(screen.getByRole('menuitem', { name: 'English' }))

    expect(await within(nav).findByText('Home')).toBeInTheDocument()
  })

  it('trasa z fullBleed wymusza tryb mini', async () => {
    await renderWithRoute('/chat/1', { fullBleed: true })

    expect(screen.getByRole('button', { name: 'Rozwiń menu' })).toBeInTheDocument()
  })

  it('trasa bez fullBleed startuje w trybie pełnym', async () => {
    await renderWithRoute('/', {})

    expect(screen.getByRole('button', { name: 'Zwiń menu' })).toBeInTheDocument()
  })
})
