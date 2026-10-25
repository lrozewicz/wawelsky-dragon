import * as React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Button from '@mui/material/Button'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import useNotifications from './useNotifications'

afterEach(cleanup)

function NotificationsTester() {
  const notifications = useNotifications()

  return (
    <React.Fragment>
      <Button onClick={() => notifications.show('Zapisano')}>pokaz</Button>
      <Button
        onClick={() => {
          notifications.show('a')
          notifications.show('b')
        }}
      >
        pokaz-dwa
      </Button>
      <Button
        onClick={() => notifications.show('x', { severity: 'success', autoHideDuration: 100 })}
      >
        pokaz-auto
      </Button>
      <Button
        onClick={() => notifications.show('z akcją', { actionText: 'Cofnij', onAction: () => {} })}
      >
        pokaz-akcja
      </Button>
      <Button onClick={() => notifications.show('domyślna akcja', { onAction: () => {} })}>
        pokaz-domyslna-akcja
      </Button>
      <Button
        onClick={() => {
          notifications.show('kluczowany', { key: 'klucz' })
          notifications.show('kluczowany duplikat', { key: 'klucz' })
        }}
      >
        pokaz-klucz
      </Button>
    </React.Fragment>
  )
}

describe('useNotifications', () => {
  it("show('Zapisano') pokazuje tekst w dokumencie", async () => {
    const user = userEvent.setup()
    await renderWithProviders(<NotificationsTester />)

    await user.click(screen.getByRole('button', { name: 'pokaz' }))

    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
  })

  it('pokazuje powiadomienia po kolei — drugie wchodzi po zamknięciu pierwszego', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<NotificationsTester />)

    await user.click(screen.getByRole('button', { name: 'pokaz-dwa' }))

    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.queryByText('b')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    await waitFor(() => expect(screen.getByText('b')).toBeInTheDocument())
    expect(screen.queryByText('a')).not.toBeInTheDocument()
  })

  it('znika po autoHideDuration', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<NotificationsTester />)

    await user.click(screen.getByRole('button', { name: 'pokaz-auto' }))
    expect(await screen.findByText('x')).toBeInTheDocument()

    await waitFor(() => expect(screen.queryByText('x')).not.toBeInTheDocument(), { timeout: 2000 })
  })

  it('przycisk akcji używa actionText, a domyślnie etykiety common.action', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<NotificationsTester />)

    await user.click(screen.getByRole('button', { name: 'pokaz-akcja' }))
    expect(await screen.findByRole('button', { name: 'Cofnij' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    await user.click(screen.getByRole('button', { name: 'pokaz-domyslna-akcja' }))
    expect(await screen.findByRole('button', { name: 'Akcja' })).toBeInTheDocument()
  })

  it('deduplikuje powiadomienia o tym samym kluczu', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<NotificationsTester />)

    await user.click(screen.getByRole('button', { name: 'pokaz-klucz' }))

    expect(await screen.findByText('kluczowany')).toBeInTheDocument()
    expect(screen.queryByText('kluczowany duplikat')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zamknij' })).toBeInTheDocument()
  })

  it('wywołanie hooka bez providera rzuca Error', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    function Broken() {
      useNotifications()
      return null
    }

    expect(() => render(<Broken />)).toThrow('Notifications context was used without a provider.')

    errorSpy.mockRestore()
  })
})
