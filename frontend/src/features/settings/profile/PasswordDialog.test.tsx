/**
 * Dialog zmiany hasła (kontrakt WP E3-6c1 §T3 p. 2): trzy pola, walidacja nowego hasła
 * (≥ 8 znaków, powtórka równa), wysyłka wyłącznie `password`/`new_password`, zamknięcie po
 * sukcesie i `Alert` z komunikatem API przy błędzie (dialog zostaje otwarty).
 */

import type { ReactNode } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ShowNotificationOptions } from '../../../hooks/useNotifications/useNotifications'
import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { PasswordDialog } from './PasswordDialog'

import type { UserEvent } from '@testing-library/user-event'

// Podsłuch powiadomień (kontrakt WP E3-H2b §C3): asercja opcji przekazanych do `show`, a wyświetlanie
// zostaje prawdziwemu providerowi — toast nadal trafia do DOM.
const { showSpy } = vi.hoisted(() => ({ showSpy: vi.fn() }))

vi.mock('../../../hooks/useNotifications/useNotifications', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../hooks/useNotifications/useNotifications')>()
  return {
    ...actual,
    default: () => {
      const notifications = actual.default()
      return {
        ...notifications,
        show: (message: ReactNode, options?: ShowNotificationOptions) => {
          showSpy(message, options)
          return notifications.show(message, options)
        },
      }
    },
  }
})

afterEach(cleanup)

beforeEach(() => {
  showSpy.mockClear()
})

/** PATCH profilu: przechwytuje ciała żądań i odpowiada sukcesem. */
function capturePatch(bodies: unknown[]) {
  return http.patch(apiUrl('/api/v1/users/me'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success', data: null })
  })
}

/** Wypełnia trzy pola hasła (obecne, nowe, powtórka). */
async function fillPasswords(
  user: UserEvent,
  values: { current: string; next: string; repeat: string },
): Promise<void> {
  await user.type(screen.getByTestId('profile-password-current'), values.current)
  await user.type(screen.getByTestId('profile-password-new'), values.next)
  await user.type(screen.getByTestId('profile-password-repeat'), values.repeat)
}

describe('PasswordDialog', () => {
  it('pola haseł mają typ `password` i `autoComplete` wg roli', async () => {
    await renderWithProviders(<PasswordDialog onClose={vi.fn()} />)

    expect(screen.getByTestId('profile-password-current')).toHaveAttribute(
      'autocomplete',
      'current-password',
    )
    expect(screen.getByTestId('profile-password-new')).toHaveAttribute(
      'autocomplete',
      'new-password',
    )
    expect(screen.getByTestId('profile-password-repeat')).toHaveAttribute(
      'autocomplete',
      'new-password',
    )
  })

  it('nowe hasło krótsze niż 8 znaków blokuje żądanie', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<PasswordDialog onClose={vi.fn()} />)

    await fillPasswords(user, { current: 'stare-haslo', next: 'abc', repeat: 'abc' })
    await user.click(screen.getByTestId('profile-password-submit'))

    expect(await screen.findByText('Nowe hasło musi mieć co najmniej 8 znaków')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('niezgodna powtórka blokuje żądanie', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<PasswordDialog onClose={vi.fn()} />)

    await fillPasswords(user, { current: 'stare-haslo', next: 'nowe-haslo', repeat: 'inne-haslo' })
    await user.click(screen.getByTestId('profile-password-submit'))

    expect(await screen.findByText('Hasła nie są identyczne')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('wysyła tylko `password` i `new_password` i zamyka dialog po sukcesie', async () => {
    const bodies: unknown[] = []
    const onClose = vi.fn()
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<PasswordDialog onClose={onClose} />)

    await fillPasswords(user, {
      current: 'stare-haslo',
      next: 'nowe-haslo',
      repeat: 'nowe-haslo',
    })
    await user.click(screen.getByTestId('profile-password-submit'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(bodies).toEqual([{ password: 'stare-haslo', new_password: 'nowe-haslo' }])
    expect(await screen.findByText('Hasło zostało zmienione')).toBeInTheDocument()
    // Kontrakt §C3: toast sukcesu znika sam po 4 s.
    expect(showSpy).toHaveBeenCalledWith('Hasło zostało zmienione', {
      severity: 'success',
      autoHideDuration: 4000,
    })
  })

  it('błąd API pokazuje `Alert` i zostawia dialog otwarty', async () => {
    const onClose = vi.fn()
    server.use(
      http.patch(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({ code: 102, message: 'wrong password', data: null }),
      ),
    )
    const user = userEvent.setup()
    await renderWithProviders(<PasswordDialog onClose={onClose} />)

    await fillPasswords(user, {
      current: 'stare-haslo',
      next: 'nowe-haslo',
      repeat: 'nowe-haslo',
    })
    await user.click(screen.getByTestId('profile-password-submit'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nie udało się wykonać operacji: wrong password')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
