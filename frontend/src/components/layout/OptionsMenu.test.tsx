import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { OptionsMenu } from './OptionsMenu'

const ROUTES = ['/user-setting/profile', '/user-setting/model']

afterEach(cleanup)

async function openMenu() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Menu użytkownika' }))
  return user
}

describe('OptionsMenu', () => {
  it('woła onLogout po kliknięciu Wyloguj', async () => {
    const onLogout = vi.fn()
    await renderWithProviders(
      <OptionsMenu onLogout={onLogout} onLanguageChange={vi.fn()} onNavigate={vi.fn()} />,
      { routes: ROUTES },
    )

    const user = await openMenu()
    await user.click(screen.getByRole('menuitem', { name: 'Wyloguj' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('woła onLanguageChange z wybranym językiem', async () => {
    const onLanguageChange = vi.fn()
    await renderWithProviders(
      <OptionsMenu onLogout={vi.fn()} onLanguageChange={onLanguageChange} onNavigate={vi.fn()} />,
      { routes: ROUTES },
    )

    const user = await openMenu()
    await user.click(screen.getByRole('menuitem', { name: 'Język' }))
    await user.click(screen.getByRole('menuitem', { name: 'English' }))
    expect(onLanguageChange).toHaveBeenCalledWith('en')
  })

  it('woła onNavigate dla profilu', async () => {
    const onNavigate = vi.fn()
    await renderWithProviders(
      <OptionsMenu onLogout={vi.fn()} onLanguageChange={vi.fn()} onNavigate={onNavigate} />,
      { routes: ROUTES },
    )

    const user = await openMenu()
    await user.click(screen.getByRole('menuitem', { name: 'Profil' }))
    expect(onNavigate).toHaveBeenCalledWith('/user-setting/profile')
  })
})
