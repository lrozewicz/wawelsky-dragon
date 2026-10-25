import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeatureFlags } from '../../lib/featureFlags'
import type { AppUser } from './types'
import { renderWithProviders } from '../../test/renderWithProviders'

import { SideMenu } from './SideMenu'

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

function renderSideMenu(overrides: { mini?: boolean; showModelsAlert?: boolean } = {}) {
  return renderWithProviders(
    <SideMenu
      pathname="/datasets"
      user={USER}
      isSuperuser={false}
      flags={HIDDEN}
      showModelsAlert={overrides.showModelsAlert ?? false}
      docsUrl=""
      mini={overrides.mini ?? false}
      onToggleMini={vi.fn()}
      onLogout={vi.fn()}
      onLanguageChange={vi.fn()}
    />,
    { route: '/datasets', routes: ROUTES },
  )
}

describe('SideMenu', () => {
  it('w trybie pełnym pokazuje nazwę aplikacji i dane użytkownika', async () => {
    await renderSideMenu()

    expect(screen.getByText('Wawelsky Dragon')).toBeInTheDocument()
    expect(screen.getByText('jan@example.com')).toBeInTheDocument()
    expect(screen.getByTitle('jan@example.com')).toBeInTheDocument()
  })

  it('w trybie mini ukrywa dane użytkownika i pokazuje przycisk rozwijania', async () => {
    await renderSideMenu({ mini: true })

    expect(screen.queryByText('jan@example.com')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rozwiń menu' })).toBeInTheDocument()
  })

  it('klik przycisku zwijania woła onToggleMini', async () => {
    const user = userEvent.setup()
    const onToggleMini = vi.fn()
    await renderWithProviders(
      <SideMenu
        pathname="/datasets"
        user={USER}
        isSuperuser={false}
        flags={HIDDEN}
        showModelsAlert={false}
        docsUrl=""
        mini={false}
        onToggleMini={onToggleMini}
        onLogout={vi.fn()}
        onLanguageChange={vi.fn()}
      />,
      { route: '/datasets', routes: ROUTES },
    )

    await user.click(screen.getByRole('button', { name: 'Zwiń menu' }))
    expect(onToggleMini).toHaveBeenCalledTimes(1)
  })

  it('pokazuje alert modeli, gdy showModelsAlert', async () => {
    await renderSideMenu({ showModelsAlert: true })
    expect(screen.getByText('Skonfiguruj modele')).toBeInTheDocument()
  })
})
