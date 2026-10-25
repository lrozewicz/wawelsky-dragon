/**
 * Paginacja serwerowa `UsersPage` bez powrotu na stronę 1 (zadanie T5, WP E3-H2b).
 * Podczas pobierania strony 2 `total` nie może spaść do 0 — inaczej `DataGrid` klampuje
 * `page` do 0 i „następna strona” cofa użytkownika na pierwszą. Test opóźnia odpowiedź
 * strony 2, żeby ta chwila była obserwowalna, i sprawdza, że wiersz strony 2 się pokazuje,
 * a żądanie `page=1` nie leci ponownie.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { adminHandlers, apiUrl, fixtureUser, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { USERS_PAGE_SIZE } from '../constants'

import { UsersPage } from './UsersPage'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Opóźnienie odpowiedzi strony 2 — okno, w którym `total` mogłoby spaść do 0. */
const PAGE_2_DELAY_MS = 100

/** Limit czasu testu wyższy od globalnego (15 s): pod pełnym obciążeniem zestawu sam start
 *  jsdom + leniwego `DataGrid` potrafi przekroczyć globalny budżet (flaki CI/hosta). */
const TEST_TIMEOUT_MS = 30_000

/** Zalogowany administrator — wiersz z seedu (`jan@wd.test`) nie jest „własny”. */
const authAdmin = { user: { ...fixtureUser, id: 'u-admin', is_superuser: true } }

/** 26 użytkowników: pierwsza strona pełna, druga ma jeden wiersz (`user-26@wd.test`). */
const USERS = Array.from({ length: USERS_PAGE_SIZE + 1 }, (_value, index) =>
  makeWdUser({
    id: `u-${String(index + 1)}`,
    email: `user-${String(index + 1)}@wd.test`,
    nickname: `User ${String(index + 1)}`,
  }),
)

/**
 * Lista użytkowników z opóźnioną stroną 2. Handler idzie przed `adminHandlers`, więc to on
 * obsługuje `GET /users`; resztę tras (m.in. klucze API) zostawia domyślnym.
 */
function delayedUsersHandlers(): HttpHandler[] {
  return [
    http.get(apiUrl('/api/wd/v1/users'), async ({ request }) => {
      const search = new URL(request.url).searchParams
      const page = Number.parseInt(search.get('page') ?? '1', 10)
      const pageSize = Number.parseInt(search.get('page_size') ?? String(USERS_PAGE_SIZE), 10)
      if (page >= 2) await delay(PAGE_2_DELAY_MS)
      const start = (page - 1) * pageSize
      return HttpResponse.json({
        data: {
          items: USERS.slice(start, start + pageSize),
          total: USERS.length,
          page,
          page_size: pageSize,
        },
      })
    }),
    ...adminHandlers({ users: USERS }),
  ]
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

/** Parametry `page` wszystkich żądań listy użytkowników (w kolejności zgłoszeń). */
function usersPageParams(calls: string[]): (string | null)[] {
  return calls
    .filter((call) => call.startsWith('GET /api/wd/v1/users?'))
    .map((call) => new URL(`http://test${call.slice('GET '.length)}`).searchParams.get('page'))
}

describe('UsersPage — paginacja bez powrotu na stronę 1', () => {
  it(
    'po kliknięciu „następna strona" pokazuje stronę 2 i nie pobiera ponownie strony 1',
    { timeout: TEST_TIMEOUT_MS },
    async () => {
      server.use(...delayedUsersHandlers())
      const calls = recordRequests()
      const user = userEvent.setup()
      await renderWithProviders(<UsersPage />, { auth: authAdmin })
      await screen.findByText('user-1@wd.test')
      expect(usersPageParams(calls)).toEqual(['1'])

      await user.click(screen.getByRole('button', { name: 'Przejdź do następnej strony' }))

      // Żądanie `page=1` nie poleciało ponownie po starcie `page=2` (bez `keepPreviousData`
      // `total` spada do 0, `DataGrid` klampuje `page` do 0 i wraca na pierwszą stronę).
      await waitFor(() => expect(usersPageParams(calls)).toEqual(['1', '2']))
      // Po opóźnionej odpowiedzi widoczny jest wiersz strony 2, a strona 1 znika.
      expect(await screen.findByText('user-26@wd.test')).toBeInTheDocument()
      expect(screen.queryByText('user-1@wd.test')).not.toBeInTheDocument()
    },
  )
})
