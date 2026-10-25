/**
 * Strona profilu (kontrakt WP E3-6c1 §T3): wiersze karty, ukrycie hasła dla kont OIDC,
 * edycja nazwy (przyciskiem i Enterem) oraz strefy czasowej, a także stany ładowania i błędu
 * odczytu. Każdy test sam ustawia `GET /api/v1/users/me` — domyślny fixture to konto lokalne
 * (`login_channel: 'password'`) bez strefy czasowej.
 */

import type { ReactNode } from 'react'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ShowNotificationOptions } from '../../../hooks/useNotifications/useNotifications'
import { apiUrl, fixtureUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ProfilePage } from './ProfilePage'

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

/** GET profilu z podmienionymi polami konta. */
function meHandler(overrides: Partial<typeof fixtureUser>) {
  return http.get(apiUrl('/api/v1/users/me'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: { ...fixtureUser, ...overrides } }),
  )
}

/** PATCH profilu: przechwytuje ciała żądań i odpowiada sukcesem. */
function capturePatch(bodies: unknown[]) {
  return http.patch(apiUrl('/api/v1/users/me'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success', data: null })
  })
}

describe('ProfilePage', () => {
  it('pokazuje wiersze profilu z danymi konta', async () => {
    await renderWithProviders(<ProfilePage />)

    expect(await screen.findByTestId('profile-row-name')).toHaveTextContent('User')
    expect(screen.getByTestId('profile-row-email')).toHaveTextContent('user@example.com')
    expect(screen.getByTestId('profile-row-timezone')).toHaveTextContent('Nie ustawiono')
    expect(screen.getByTestId('profile-row-password')).toHaveTextContent('Hasło')
  })

  it('e-mail jest tylko do odczytu, pozostałe wiersze mają „Edytuj”', async () => {
    await renderWithProviders(<ProfilePage />)

    expect(within(await screen.findByTestId('profile-row-email')).queryByRole('button')).toBeNull()
    expect(screen.getByTestId('profile-edit-name')).toHaveTextContent('Edytuj')
    expect(screen.getByTestId('profile-edit-timezone')).toHaveTextContent('Edytuj')
    expect(screen.getByTestId('profile-edit-password')).toHaveTextContent('Edytuj')
  })

  it('pokazuje ustawioną strefę czasową', async () => {
    server.use(meHandler({ timezone: 'Europe/Warsaw' }))
    await renderWithProviders(<ProfilePage />)

    expect(await screen.findByTestId('profile-row-timezone')).toHaveTextContent('Europe/Warsaw')
  })

  it('edytuje nazwę i wysyła tylko `nickname`', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-name'))
    const field = await screen.findByTestId('profile-name-input')
    // Dostępność (kontrakt §T3 p. 6): pole dostaje fokus, a dialog ma nazwę z `DialogTitle`.
    expect(field).toHaveFocus()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-labelledby')
    await user.clear(field)
    await user.type(field, 'Jan')
    await user.click(screen.getByTestId('profile-name-submit'))

    await waitFor(() => expect(bodies).toEqual([{ nickname: 'Jan' }]))
    expect(await screen.findByText('Zapisano zmiany')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
    // Kontrakt §C3: toast sukcesu znika sam po 4 s (jak w pozostałych powiadomieniach).
    expect(showSpy).toHaveBeenCalledWith('Zapisano zmiany', {
      severity: 'success',
      autoHideDuration: 4000,
    })
  })

  it('Alert błędu zapisu nie wraca po zamknięciu i ponownym otwarciu dialogu', async () => {
    server.use(
      http.patch(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({ code: 102, message: 'nazwa zajęta', data: null }),
      ),
    )
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-name'))
    await user.clear(await screen.findByTestId('profile-name-input'))
    await user.type(screen.getByTestId('profile-name-input'), 'Jan')
    await user.click(screen.getByTestId('profile-name-submit'))
    expect(await screen.findByRole('alert')).toHaveTextContent('nazwa zajęta')

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))
    await user.click(await screen.findByTestId('profile-edit-name'))

    expect(screen.getByTestId('profile-name-input')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('nazwa z samych spacji (po trim) blokuje żądanie', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-name'))
    const field = await screen.findByTestId('profile-name-input')
    await user.clear(field)
    await user.type(field, '   ')
    await user.click(screen.getByTestId('profile-name-submit'))

    expect(await screen.findByText('Nazwa jest wymagana')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('nazwa dłuższa niż 128 znaków blokuje żądanie', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-name'))
    const field = await screen.findByTestId('profile-name-input')
    await user.clear(field)
    await user.type(field, 'a'.repeat(129))
    await user.click(screen.getByTestId('profile-name-submit'))

    expect(await screen.findByText('Nazwa może mieć najwyżej 128 znaków')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('Enter w polu nazwy zatwierdza dialog', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-name'))
    const field = await screen.findByTestId('profile-name-input')
    await user.clear(field)
    await user.type(field, 'Jan{Enter}')

    await waitFor(() => expect(bodies).toEqual([{ nickname: 'Jan' }]))
  })

  it('edytuje strefę czasową i wysyła tylko `timezone`', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const user = userEvent.setup()
    await renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByTestId('profile-edit-timezone'))
    await user.type(await screen.findByRole('combobox'), 'Europe/Warsaw')
    await user.click(screen.getByTestId('profile-timezone-submit'))

    await waitFor(() => expect(bodies).toEqual([{ timezone: 'Europe/Warsaw' }]))
    // Kontrakt §C3: toast sukcesu znika sam po 4 s.
    expect(showSpy).toHaveBeenCalledWith('Zapisano zmiany', {
      severity: 'success',
      autoHideDuration: 4000,
    })
  })

  it('ukrywa wiersz hasła dla kont OIDC (bez `Alert`)', async () => {
    server.use(meHandler({ login_channel: 'keycloak' }))
    await renderWithProviders(<ProfilePage />)

    expect(await screen.findByTestId('profile-row-name')).toBeInTheDocument()
    expect(screen.queryByTestId('profile-row-password')).toBeNull()
    expect(screen.getByTestId('profile-row-email')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('pokazuje `Skeleton`, dopóki profil się ładuje', async () => {
    server.use(
      http.get(apiUrl('/api/v1/users/me'), async () => {
        await delay(50)
        return HttpResponse.json({ code: 0, message: 'success', data: fixtureUser })
      }),
    )
    await renderWithProviders(<ProfilePage />)

    expect(screen.getByTestId('profile-loading')).toBeInTheDocument()
    expect(await screen.findByTestId('profile-row-name')).toBeInTheDocument()
  })

  it('pokazuje `Alert` z komunikatem API, gdy odczyt się nie powiedzie', async () => {
    server.use(
      http.get(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({ code: 102, message: 'profile unavailable', data: null }),
      ),
    )
    await renderWithProviders(<ProfilePage />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nie udało się wykonać operacji: profile unavailable')
  })
})
