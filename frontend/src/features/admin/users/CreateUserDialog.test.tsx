/**
 * Dialog tworzenia użytkownika (kontrakt WP E3-6c2 §T3 pkt 6): wymagany e-mail (U11 — aktywny
 * przycisk, komunikat i fokus przy pustym polu, format po opuszczeniu), blokada w trakcie
 * tworzenia (`loading`), zamknięcie po sukcesie oraz komunikat konfliktu (zajęty e-mail)
 * zostawiony w otwartym dialogu.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { CreateUserDialog } from './CreateUserDialog'

afterEach(cleanup)

describe('CreateUserDialog', () => {
  it('przycisk zapisu pozostaje aktywny; klik bez e-maila pokazuje komunikat i wraca fokusem (U11)', async () => {
    await renderWithProviders(<CreateUserDialog open onClose={vi.fn()} />)
    const user = userEvent.setup()

    expect(screen.getByTestId('admin-create-user-submit')).toBeEnabled()
    await user.click(screen.getByTestId('admin-create-user-submit'))

    const field = screen.getByRole('textbox', { name: /E-mail/ })
    expect(field).toHaveFocus()
    expect(screen.getByText('Pole wymagane')).toBeInTheDocument()
    // Etykieta zostaje nad polem (shrink), choć pole jest puste.
    expect(field.closest('.MuiFormControl-root')?.querySelector('.MuiInputLabel-root')).toHaveClass(
      'MuiInputLabel-shrink',
    )

    // Wpisanie wartości gasi komunikat od razu.
    await user.type(field, 'n')
    expect(screen.queryByText('Pole wymagane')).not.toBeInTheDocument()
  })

  it('błędny format e-maila pokazuje komunikat po opuszczeniu pola, a klik wraca fokusem (U11)', async () => {
    await renderWithProviders(<CreateUserDialog open onClose={vi.fn()} />)
    const user = userEvent.setup()
    const field = screen.getByRole('textbox', { name: /E-mail/ })

    // Przed opuszczeniem pola formularz milczy.
    await user.type(field, 'niepoprawny-mail')
    expect(screen.queryByText('Podaj poprawny adres e-mail.')).not.toBeInTheDocument()

    await user.tab()
    expect(screen.getByText('Podaj poprawny adres e-mail.')).toBeInTheDocument()

    // Przycisk pozostaje aktywny; klik wraca fokusem do błędnego pola.
    expect(screen.getByTestId('admin-create-user-submit')).toBeEnabled()
    await user.click(screen.getByTestId('admin-create-user-submit'))
    expect(field).toHaveFocus()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('podwójna kropka w domenie („a@b..c”) odrzuca e-mail — sprawdzenie jak w authForm (T3)', async () => {
    await renderWithProviders(<CreateUserDialog open onClose={vi.fn()} />)
    const user = userEvent.setup()
    const field = screen.getByRole('textbox', { name: /E-mail/ })

    // Stary wzorzec `[^\s@]+\.[^\s@]+` przepuszczał kolejne kropki w domenie.
    await user.type(field, 'a@b..c')
    await user.tab()

    expect(screen.getByText('Podaj poprawny adres e-mail.')).toBeInTheDocument()
  })

  it('tworzy konto i zamyka dialog', async () => {
    const onClose = vi.fn()
    const bodies: unknown[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/users'), async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(
          { data: makeWdUser({ id: 'u-3', email: 'nowy@wd.test' }) },
          { status: 201 },
        )
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<CreateUserDialog open onClose={onClose} />)

    await user.type(screen.getByRole('textbox', { name: /E-mail/ }), 'nowy@wd.test')
    await user.type(screen.getByLabelText('Nazwa'), 'Nowy')
    await user.click(screen.getByTestId('admin-create-user-submit'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(bodies).toEqual([
      { email: 'nowy@wd.test', password: null, nickname: 'Nowy', is_superuser: false },
    ])
  })

  it('przy zajętym e-mailu pokazuje komunikat konfliktu i nie zamyka dialogu', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(<CreateUserDialog open onClose={onClose} />)

    await user.type(screen.getByRole('textbox', { name: /E-mail/ }), 'admin@wd.test')
    await user.click(screen.getByTestId('admin-create-user-submit'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Operacja niedozwolona: konflikt')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('blokuje przycisk w trakcie zapisu', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/users'), async () => {
        await delay(50)
        return HttpResponse.json({ data: makeWdUser({ id: 'u-9' }) }, { status: 201 })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<CreateUserDialog open onClose={vi.fn()} />)

    await user.type(screen.getByRole('textbox', { name: /E-mail/ }), 'nowy@wd.test')
    await user.click(screen.getByTestId('admin-create-user-submit'))

    // `loading` zamiast `disabled` (U11) — stan `isPending` przeluje się po kliknięciu.
    await waitFor(() => {
      expect(screen.getByTestId('admin-create-user-submit')).toBeDisabled()
    })
  })
})
