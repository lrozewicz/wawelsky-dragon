import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeatureFlags } from '../../lib/featureFlags'
import { renderWithProviders } from '../../test/renderWithProviders'

import { SideMenuMobile } from './SideMenuMobile'
import type { AppUser } from './types'

const HIDDEN: FeatureFlags = { agent: false, memory: false, search: true, files: true }
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

function renderMobile(overrides: { open?: boolean; onClose?: () => void } = {}) {
  return renderWithProviders(
    <SideMenuMobile
      open={overrides.open ?? true}
      onClose={overrides.onClose ?? vi.fn()}
      pathname="/datasets"
      user={USER}
      isSuperuser={false}
      flags={HIDDEN}
      showModelsAlert={false}
      docsUrl=""
      onLogout={vi.fn()}
      onLanguageChange={vi.fn()}
      onNavigate={vi.fn()}
    />,
    { route: '/datasets', routes: ROUTES },
  )
}

describe('SideMenuMobile', () => {
  it('po otwarciu pokazuje nawigację i danych użytkownika', async () => {
    await renderMobile()

    expect(screen.getByRole('navigation', { name: 'Nawigacja główna' })).toBeInTheDocument()
    expect(screen.getByText('Jan Kowalski')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zamknij menu' })).toBeInTheDocument()
  })

  it('klik przycisku zamknięcia woła onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderMobile({ onClose })

    await user.click(screen.getByRole('button', { name: 'Zamknij menu' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('klik pozycji nawigacji zamyka menu', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderMobile({ onClose })

    await user.click(screen.getByRole('link', { name: 'Bazy wiedzy' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('klik Wyloguj woła onLogout', async () => {
    const user = userEvent.setup()
    const onLogout = vi.fn()
    await renderWithProviders(
      <SideMenuMobile
        open
        onClose={vi.fn()}
        pathname="/datasets"
        user={USER}
        isSuperuser={false}
        flags={HIDDEN}
        showModelsAlert={false}
        docsUrl=""
        onLogout={onLogout}
        onLanguageChange={vi.fn()}
        onNavigate={vi.fn()}
      />,
      { route: '/datasets', routes: ROUTES },
    )

    await user.click(screen.getByRole('button', { name: 'Wyloguj' }))

    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('zamknięte menu nie renderuje nawigacji', async () => {
    await renderMobile({ open: false })

    expect(screen.queryByRole('navigation', { name: 'Nawigacja główna' })).not.toBeInTheDocument()
  })
})
