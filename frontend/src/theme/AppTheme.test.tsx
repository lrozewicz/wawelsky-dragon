import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { initI18n } from '../i18n'

import AppTheme from './AppTheme'
import ColorModeIconDropdown from './ColorModeIconDropdown'
import ColorModeSelect from './ColorModeSelect'

beforeAll(async () => {
  await initI18n('pl')
})

afterEach(() => {
  document.documentElement.removeAttribute('data-mui-color-scheme')
})

describe('AppTheme', () => {
  it('renderuje dziecko', () => {
    render(
      <AppTheme>
        <span>hello</span>
      </AppTheme>,
    )

    expect(screen.getByText('hello')).toBeInTheDocument()
  })

  it('przełącza tryb ciemny i jasny przez ColorModeIconDropdown', async () => {
    const user = userEvent.setup()
    render(
      <AppTheme>
        <ColorModeIconDropdown />
      </AppTheme>,
    )

    await user.click(screen.getByRole('button', { name: 'Tryb kolorów' }))
    await user.click(screen.getByRole('menuitem', { name: 'Ciemny' }))
    expect(document.documentElement.getAttribute('data-mui-color-scheme')).toBe('dark')

    await user.click(screen.getByRole('button', { name: 'Tryb kolorów' }))
    await user.click(screen.getByRole('menuitem', { name: 'Jasny' }))
    expect(document.documentElement.getAttribute('data-mui-color-scheme')).toBe('light')
  })

  it('renderuje ColorModeSelect bez błędów konsoli', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <AppTheme>
        <ColorModeSelect />
      </AppTheme>,
    )

    expect(errorSpy).not.toHaveBeenCalled()
    errorSpy.mockRestore()
  })
})
