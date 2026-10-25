import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { Header } from './Header'

afterEach(cleanup)

describe('Header', () => {
  it('pokazuje okruszki aktywnej pozycji', async () => {
    await renderWithProviders(<Header pathname="/datasets" onLanguageChange={vi.fn()} />, {
      route: '/datasets',
    })

    expect(screen.getByText('Wawelsky Dragon')).toBeInTheDocument()
    expect(screen.getByText('Bazy wiedzy')).toBeInTheDocument()
  })

  it('pokazuje przycisk przełączania trybu kolorów', async () => {
    await renderWithProviders(<Header pathname="/" onLanguageChange={vi.fn()} />, { route: '/' })

    expect(screen.getByRole('button', { name: 'Tryb kolorów' })).toBeInTheDocument()
  })

  it('wybór języka woła onLanguageChange', async () => {
    const user = userEvent.setup()
    const onLanguageChange = vi.fn()
    await renderWithProviders(<Header pathname="/" onLanguageChange={onLanguageChange} />, {
      route: '/',
    })

    await user.click(screen.getByRole('button', { name: 'Język' }))
    await user.click(screen.getByRole('menuitem', { name: 'English' }))

    expect(onLanguageChange).toHaveBeenCalledWith('en')
  })
})
