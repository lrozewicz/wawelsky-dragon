/**
 * Dialog zmiany hasła (kontrakt WP E3-6c2 §T4 pkt 2): komunikat dla kont nielokalnych, brak pola
 * hasła w tym wariancie, wysyłka `{new_password}` na trasę hasła i zamknięcie po sukcesie.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { PasswordDialog } from './PasswordDialog'

afterEach(cleanup)

describe('PasswordDialog', () => {
  it('dla konta oidc pokazuje onlyLocal i nie daje pola hasła', async () => {
    await renderWithProviders(
      <PasswordDialog open user={makeWdUser({ auth_source: 'oidc' })} onClose={vi.fn()} />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Hasło można zmienić tylko dla kont lokalnych.',
    )
    expect(screen.queryByLabelText('Nowe hasło')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zmień hasło' })).not.toBeInTheDocument()
  })

  it('wysyła nowe hasło i zamyka dialog', async () => {
    const onClose = vi.fn()
    const bodies: unknown[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/password'), async ({ request }) => {
        bodies.push(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(
      <PasswordDialog open user={makeWdUser({ id: 'u-jan' })} onClose={onClose} />,
    )

    await user.type(screen.getByLabelText('Nowe hasło'), 'tajne-haslo')
    await user.click(screen.getByRole('button', { name: 'Zmień hasło' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(bodies).toEqual([{ new_password: 'tajne-haslo' }])
  })

  it('pokazuje Alert z komunikatem konfliktu, gdy backend odmówi', async () => {
    const onClose = vi.fn()
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/password'), () =>
        HttpResponse.json({ error: { code: 'conflict', message: 'x' } }, { status: 409 }),
      ),
    )
    const user = userEvent.setup()
    await renderWithProviders(
      <PasswordDialog open user={makeWdUser({ id: 'u-jan' })} onClose={onClose} />,
    )

    await user.type(screen.getByLabelText('Nowe hasło'), 'x')
    await user.click(screen.getByRole('button', { name: 'Zmień hasło' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Operacja niedozwolona: konflikt')
    expect(onClose).not.toHaveBeenCalled()
  })
})
