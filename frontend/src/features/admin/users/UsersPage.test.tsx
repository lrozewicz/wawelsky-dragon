/**
 * Strona użytkowników (kontrakt WP E3-6c2 §T3): kolumny i wiersze listy, szukanie z debounce
 * 300 ms, przełącznik „Aktywny”, nadanie/odebranie administratora, blokada akcji na własnym
 * koncie, tworzenie konta oraz stany pusty i błędu listy.
 */

import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { adminHandlers, apiUrl, fixtureUser, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { stubNarrowViewport } from '../../../test/stubNarrowViewport'

import { UsersPage } from './UsersPage'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
  vi.unstubAllGlobals()
})

/** Wiersz siatki z podanym e-mailem. */
function rowFor(email: string): HTMLElement {
  const row = screen.getByText(email).closest('[role="row"]')
  if (row === null) throw new Error(`Brak wiersza dla ${email}`)
  return row as HTMLElement
}

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Zalogowany administrator z seedu — wiersz `admin@wd.test` jest „własny”. */
const authAdmin = { user: { ...fixtureUser, id: 'u-admin', is_superuser: true } }

/** Zalogowane inne konto — pozwala działać na wierszu administratora. */
const authJan = { user: { ...fixtureUser, id: 'u-jan', is_superuser: true } }

describe('UsersPage', () => {
  it('pokazuje wiersze i kolumny kontraktu', async () => {
    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    expect(await screen.findByText('admin@wd.test')).toBeInTheDocument()
    expect(screen.getByText('jan@wd.test')).toBeInTheDocument()

    for (const header of ['E-mail', 'Nazwa', 'Rola', 'Źródło', 'Aktywny', 'Utworzono', 'Akcje']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(header) })).toBeInTheDocument()
    }

    expect(within(rowFor('admin@wd.test')).getByText('Administrator')).toBeInTheDocument()
    expect(within(rowFor('jan@wd.test')).getByText('Użytkownik')).toBeInTheDocument()
    expect(within(rowFor('jan@wd.test')).getByText('Lokalne')).toBeInTheDocument()
  })

  it('zawęża listę po frazie dopiero po 300 ms', async () => {
    const calls = recordRequests()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    expect(await screen.findByText('jan@wd.test')).toBeInTheDocument()

    fireEvent.change(within(screen.getByTestId('admin-users-search')).getByRole('textbox'), {
      target: { value: 'jan' },
    })

    // Debounce: tuż po wpisaniu lista jest jeszcze pełna i żądanie z frazą nie poszło.
    expect(screen.getByText('admin@wd.test')).toBeInTheDocument()
    expect(calls.some((call) => call.includes('q=jan'))).toBe(false)

    await waitFor(() => expect(screen.queryByText('admin@wd.test')).not.toBeInTheDocument())
    expect(screen.getByText('jan@wd.test')).toBeInTheDocument()
    expect(
      calls.some((call) => call.startsWith('GET /api/wd/v1/users?') && call.includes('q=jan')),
    ).toBe(true)
  })

  it('wyłącza konto przełącznikiem „Aktywny”', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    const toggle = await screen.findByRole('switch', { name: 'jan@wd.test' })
    expect(toggle).toBeChecked()

    await user.click(toggle)

    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'jan@wd.test' })).not.toBeChecked(),
    )
    expect(calls).toContain('POST /api/wd/v1/users/u-jan/deactivate')
  })

  it('blokuje przełącznik i akcje na własnym koncie', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    expect(await screen.findByRole('switch', { name: 'admin@wd.test' })).toBeDisabled()

    await user.click(screen.getByTestId('admin-user-actions-u-admin'))

    expect(await screen.findByRole('menuitem', { name: 'Odbierz administratora' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.getByRole('menuitem', { name: 'Usuń' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('nadaje administratora z menu i pokazuje chip „Administrator”', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    await screen.findByText('jan@wd.test')
    await user.click(screen.getByTestId('admin-user-actions-u-jan'))
    await user.click(await screen.findByRole('menuitem', { name: 'Nadaj administratora' }))

    await waitFor(() =>
      expect(within(rowFor('jan@wd.test')).getByText('Administrator')).toBeInTheDocument(),
    )
    expect(calls).toContain('PATCH /api/wd/v1/users/u-jan')
  })

  it('pokazuje Alert, gdy odebranie admina łamie regułę ostatniego administratora', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authJan })

    await screen.findByText('admin@wd.test')
    await user.click(screen.getByTestId('admin-user-actions-u-admin'))
    await user.click(await screen.findByRole('menuitem', { name: 'Odbierz administratora' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Operacja niedozwolona: konflikt')
  })

  it('dodaje konto z dialogu i pokazuje je na liście', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    await user.click(screen.getByTestId('admin-users-new'))
    // Regex, bo `required` dokłada do etykiety gwiazdkę (`E-mail *`).
    await user.type(await screen.findByRole('textbox', { name: /E-mail/ }), 'nowy@wd.test')
    await user.click(screen.getByTestId('admin-create-user-submit'))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(await screen.findByText('nowy@wd.test')).toBeInTheDocument()
  })

  it('pokazuje stan pusty, gdy backend nie zwraca kont', async () => {
    server.use(...adminHandlers({ users: [] }))

    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    expect(await screen.findByTestId('empty-state')).toHaveTextContent('Brak użytkowników.')
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/wd/v1/users'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: 'upstream_error', message: 'x' } },
            { status: 500 },
          )
        }
        return HttpResponse.json({
          data: {
            items: [makeWdUser({ id: 'u-jan', email: 'jan@wd.test' })],
            total: 1,
            page: 1,
            page_size: 15,
          },
        })
      }),
    )
    const user = userEvent.setup()

    await renderWithProviders(<UsersPage />, { auth: authAdmin })

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać danych.',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('jan@wd.test')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('na wąskim ekranie akcje są pierwszą kolumną jako menu ⋮', async () => {
    stubNarrowViewport()
    await renderWithProviders(<UsersPage />, { auth: authAdmin })
    await screen.findByText('jan@wd.test')

    expect(screen.getAllByRole('columnheader')[0]).toHaveAttribute('data-field', 'actions')
    expect(screen.getAllByTestId('row-actions-menu').length).toBeGreaterThan(0)
    // Wersja desktopowa (menu per użytkownik) nie renderuje się w trybie compact.
    expect(screen.queryByTestId('admin-user-actions-u-jan')).not.toBeInTheDocument()
  })
})
