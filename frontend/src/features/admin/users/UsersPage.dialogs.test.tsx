/**
 * Podpięcie dialogów akcji w `UsersPage` (kontrakt WP E3-6c2 §T4 pkt 6, WP E3-H2b §C2): każda
 * pozycja menu wiersza (szczegóły, hasło, klucze API, usuń) otwiera właściwy dialog z danymi
 * użytkownika, a zamknięcie wraca do listy. Dialog montujemy TYLKO dla wybranej pozycji — okno
 * kluczy od razu pobiera listę, więc nie może wisieć w drzewie przy usuwaniu konta. Ostatni blok
 * to serwerowa paginacja siatki (druga strona = `GET /users?page=2`).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { adminHandlers, fixtureUser, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { UsersPage } from './UsersPage'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Zalogowany administrator z seedu — wiersz `jan@wd.test` nie jest „własny”. */
const authAdmin = { user: { ...fixtureUser, id: 'u-admin', is_superuser: true } }

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Parametry `page` wszystkich żądań listy użytkowników (w kolejności zgłoszeń). */
function usersPageParams(calls: string[]): (string | null)[] {
  return calls
    .filter((call) => call.startsWith('GET /api/wd/v1/users?'))
    .map((call) => new URL(`http://test${call.slice('GET '.length)}`).searchParams.get('page'))
}

/** Otwiera menu wiersza i wybiera pozycję o podanej nazwie. */
async function pickAction(
  user: ReturnType<typeof userEvent.setup>,
  item: string,
): Promise<HTMLElement> {
  await user.click(screen.getByTestId('admin-user-actions-u-jan'))
  await user.click(await screen.findByRole('menuitem', { name: item }))
  return screen.findByRole('dialog')
}

describe('UsersPage — dialogi akcji', () => {
  it('otwiera dialog kluczy API z e-mailem użytkownika w tytule', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    const dialog = await pickAction(user, 'Klucze API')

    expect(dialog).toHaveTextContent('Klucze API: jan@wd.test')
  })

  it('otwiera dialog szczegółów użytkownika', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    const dialog = await pickAction(user, 'Szczegóły')

    expect(dialog).toHaveTextContent('Szczegóły użytkownika')
  })

  it('otwiera dialog zmiany hasła', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    const dialog = await pickAction(user, 'Zmień hasło')

    expect(dialog).toHaveTextContent('Zmiana hasła')
  })

  it('otwiera dialog usunięcia i zamyka go bez usuwania konta', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    const dialog = await pickAction(user, 'Usuń')
    expect(dialog).toHaveTextContent('Usunąć użytkownika?')

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText('jan@wd.test')).toBeInTheDocument()
  })

  it('przy usuwaniu nie pobiera kluczy API użytkownika (dialog kluczy nie jest montowany)', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    const dialog = await pickAction(user, 'Usuń')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() =>
      expect(calls.some((call) => call.startsWith('DELETE /api/wd/v1/users/u-jan'))).toBe(true),
    )
    await waitFor(() => expect(screen.queryByText('jan@wd.test')).not.toBeInTheDocument())
    expect(calls.some((call) => call.includes('/api-keys'))).toBe(false)
  })
})

describe('UsersPage — paginacja serwerowa', () => {
  it('„następna strona" pobiera drugą stronę listy (`page=2`)', async () => {
    const users = Array.from({ length: 26 }, (_value, index) =>
      makeWdUser({
        id: `u-${String(index + 1)}`,
        email: `user-${String(index + 1)}@wd.test`,
        nickname: `User ${String(index + 1)}`,
      }),
    )
    server.use(...adminHandlers({ users }))
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('user-1@wd.test')
    expect(screen.queryByText('user-26@wd.test')).not.toBeInTheDocument()

    // `UsersGrid` ustawia teraz `localeText` (wspólny hook `useDataGridLocaleText`), więc w języku
    // polskim stopka paginacji `DataGrid` ma polskie etykiety („Przejdź do następnej strony”).
    expect(screen.queryByText('Rows per page:')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Przejdź do następnej strony' }))

    await waitFor(() => expect(usersPageParams(calls)).toContain('2'))
  })
})
