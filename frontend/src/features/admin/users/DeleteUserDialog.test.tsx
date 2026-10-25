/**
 * Dialog usunięcia użytkownika (kontrakt WP E3-6c2 §T4 pkt 4): treść z e-mailem, tryb domyślny
 * `transfer`, wysyłka wybranego trybu jako `mode` i zamknięcie po sukcesie.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { adminHandlers, apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DeleteUserDialog } from './DeleteUserDialog'

// Świeży stan handlerów przed każdym testem: mutacje z poprzedniego testu zmieniają domknięcie
// domyślnego seedu, więc usunięte konto nie wracałoby na listę.
beforeEach(() => {
  server.use(...adminHandlers())
})

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

const jan = makeWdUser({ id: 'u-jan', email: 'jan@wd.test' })

describe('DeleteUserDialog', () => {
  it('usuwa konto w trybie cascade i zamyka dialog', async () => {
    const onClose = vi.fn()
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<DeleteUserDialog open user={jan} onClose={onClose} />)

    expect(screen.getByText('Konto jan@wd.test zostanie usunięte.')).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'Usuń razem z kontem' }))
    await user.click(screen.getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(calls).toContain('DELETE /api/wd/v1/users/u-jan?mode=cascade')
  })

  it('domyślnie przenosi zasoby (transfer)', async () => {
    const onClose = vi.fn()
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<DeleteUserDialog open user={jan} onClose={onClose} />)

    expect(screen.getByRole('radio', { name: 'Przenieś do administratora' })).toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(calls).toContain('DELETE /api/wd/v1/users/u-jan?mode=transfer')
  })

  it('pokazuje Alert i nie zamyka dialogu, gdy usunięcie łamie regułę ostatniego administratora', async () => {
    server.use(
      http.delete(apiUrl('/api/wd/v1/users/:userId'), () =>
        HttpResponse.json({ error: { code: 'conflict', message: 'x' } }, { status: 409 }),
      ),
    )
    const onClose = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(
      <DeleteUserDialog
        open
        user={makeWdUser({ id: 'u-admin', email: 'admin@wd.test', is_superuser: true })}
        onClose={onClose}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Usuń' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Operacja niedozwolona: konflikt')
    expect(onClose).not.toHaveBeenCalled()
  })
})
