import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeatureFlags } from '../../lib/featureFlags'
import type { AppUser } from './types'
import { renderWithProviders } from '../../test/renderWithProviders'

import { AppNavbar } from './AppNavbar'

const ALL_OFF: FeatureFlags = { agent: false, memory: false, search: false, files: false }
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

afterEach(cleanup)

function renderNavbar() {
  return renderWithProviders(
    <AppNavbar
      pathname="/datasets"
      user={USER}
      isSuperuser={false}
      flags={ALL_OFF}
      showModelsAlert={false}
      docsUrl=""
      onLogout={vi.fn()}
      onLanguageChange={vi.fn()}
      onNavigate={vi.fn()}
    />,
    { route: '/datasets', routes: ROUTES },
  )
}

describe('AppNavbar', () => {
  it('pokazuje logo aplikacji i przycisk otwarcia menu', async () => {
    await renderNavbar()

    expect(screen.getByRole('img', { name: 'Wawelsky Dragon' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Otwórz menu' })).toBeInTheDocument()
  })

  it('nazwa aplikacji nie zawija się do drugiej linii (baner 390 px)', async () => {
    await renderNavbar()

    // Zawinięty tytuł rozdymał baner ponad rezerwę `mt: { xs: 8 }` w `AppLayout` — treść
    // chowała się pod paskiem (SC-E5-H8c-05). `noWrap` wymusza jedną linię z wielokropkiem.
    expect(screen.getByText('Wawelsky Dragon')).toHaveClass('MuiTypography-noWrap')
  })

  it('klik hamburgera otwiera nawigację główną', async () => {
    const user = userEvent.setup()
    await renderNavbar()

    await user.click(screen.getByRole('button', { name: 'Otwórz menu' }))

    expect(screen.getByRole('navigation', { name: 'Nawigacja główna' })).toBeInTheDocument()
  })
})
