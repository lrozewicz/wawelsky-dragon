/**
 * Dialog kluczy API (kontrakt WP E3-6c2 §T4 pkt 5, WP E3-H2b §C2): tworzenie klucza z tokenem
 * pokazywanym raz, lista bez tokenu, brak tokenu po zamknięciu i ponownym otwarciu, komórka
 * „Wygasa”, usuwanie, kopiowanie tokenu oraz `QueryError` błędu pobrania listy z ponowieniem.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { adminHandlers, apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { ApiKey } from '../queries'

import { ApiKeysDialog } from './ApiKeysDialog'

// Świeży stan handlerów przed każdym testem: klucze dopisane w jednym teście nie mogą
// przeciekać do kolejnego (domknięcie `adminHandlers` żyje między testami).
beforeEach(() => {
  server.use(...adminHandlers())
})

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

const TS = '2025-01-01T00:00:00Z'
const jan = makeWdUser({ id: 'u-jan', email: 'jan@wd.test' })

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Lista kluczy z zadanego zbioru — tokenu nie ma w odpowiedzi GET (kontrakt §0). */
function listKeys(items: ApiKey[]) {
  return http.get(apiUrl('/api/wd/v1/users/:userId/api-keys'), () =>
    HttpResponse.json({ data: { items } }),
  )
}

/** Dialog trzymany w stanie rodzica — pozwala zamknąć go i otworzyć ponownie bez odmontowania. */
function Harness({ user }: { user: typeof jan }): JSX.Element {
  const [open, setOpen] = useState(true)

  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <ApiKeysDialog open={open} user={user} onClose={() => setOpen(false)} />
    </>
  )
}

describe('ApiKeysDialog', () => {
  it('tworzy klucz z nazwą, pokazuje token i listę bez tokenu', async () => {
    const bodies: unknown[] = []
    const keys: ApiKey[] = []
    server.use(
      listKeys(keys),
      http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), async ({ request }) => {
        const body = (await request.json()) as { name?: string }
        bodies.push(body)
        keys.push({
          id: 'key-1',
          name: body.name ?? null,
          prefix: 'wdk-000000000001',
          created_at: TS,
          last_used_at: null,
          expires_at: null,
        })
        return HttpResponse.json(
          { data: { ...keys[0], token: 'wdk-000000000001-secret' } },
          { status: 201 },
        )
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)
    expect(await screen.findByText('Brak kluczy API.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Nazwa klucza'), 'ci')
    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))

    expect(await screen.findByTestId('admin-key-token')).toHaveTextContent(
      'wdk-000000000001-secret',
    )
    expect(await screen.findByRole('cell', { name: 'ci' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'wdk-000000000001' })).toBeInTheDocument()
    expect(screen.queryByRole('cell', { name: 'wdk-000000000001-secret' })).not.toBeInTheDocument()
    expect(bodies).toEqual([{ name: 'ci' }])
  })

  it('po zamknięciu i ponownym otwarciu nie pokazuje już tokenu', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<Harness user={jan} />)

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    await screen.findByTestId('admin-key-token')

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))
    // Przycisk poza modalem: `getByText`, bo otwarty `Dialog` ukrywa resztę drzewa przed ARIA.
    await user.click(screen.getByText('reopen'))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByTestId('admin-key-token')).not.toBeInTheDocument()
  })

  it('pokazuje „Wygasł” dla daty z przeszłości i „Bezterminowy” dla braku daty', async () => {
    server.use(
      listKeys([
        {
          id: 'key-old',
          name: 'stary',
          prefix: 'wdk-old',
          created_at: TS,
          last_used_at: null,
          expires_at: '2020-01-01T00:00:00Z',
        },
        {
          id: 'key-new',
          name: 'wieczny',
          prefix: 'wdk-new',
          created_at: TS,
          last_used_at: TS,
          expires_at: null,
        },
      ]),
    )

    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    expect(await screen.findByText('Wygasł')).toBeInTheDocument()
    expect(screen.getByText('Bezterminowy')).toBeInTheDocument()
  })

  it('usuwa klucz przyciskiem z wiersza', async () => {
    const calls = recordRequests()
    server.use(
      listKeys([
        {
          id: 'key-1',
          name: 'ci',
          prefix: 'wdk-000000000001',
          created_at: TS,
          last_used_at: null,
          expires_at: null,
        },
      ]),
      http.delete(
        apiUrl('/api/wd/v1/users/:userId/api-keys/:keyId'),
        () => new HttpResponse(null, { status: 204 }),
      ),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: 'Usuń klucz' }))

    await waitFor(() => expect(calls).toContain('DELETE /api/wd/v1/users/u-jan/api-keys/key-1'))
  })

  it('kopiuje utworzony token i zmienia etykietę przycisku na „Skopiowano”', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), () =>
        HttpResponse.json(
          {
            data: {
              id: 'key-1',
              name: 'ci',
              prefix: 'wdk-000000000001',
              created_at: TS,
              last_used_at: null,
              expires_at: null,
              token: 'wdk-000000000001-secret',
            },
          },
          { status: 201 },
        ),
      ),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    await screen.findByTestId('admin-key-token')

    await user.click(screen.getByRole('button', { name: 'Kopiuj' }))

    // `userEvent` podstawia własny schowek — tekst czytamy z niego (wzór `CreateKeyDialog.test.tsx`).
    await expect(navigator.clipboard.readText()).resolves.toBe('wdk-000000000001-secret')
    expect(screen.getByRole('button', { name: 'Skopiowano' })).toBeInTheDocument()
  })

  it('przy porażce kopiowania pokazuje komunikat i zaznacza token (SC-E5-H9-08)', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), () =>
        HttpResponse.json(
          {
            data: {
              id: 'key-1',
              name: 'ci',
              prefix: 'wdk-000000000001',
              created_at: TS,
              last_used_at: null,
              expires_at: null,
              token: 'wdk-000000000001-secret',
            },
          },
          { status: 201 },
        ),
      ),
    )

    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)
    const user = userEvent.setup()
    // Oba mechanizmy zawodzą: schowek odrzuca, `execCommand` zwraca false (jak w s24-h9-b).
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: () => Promise.reject(new DOMException('odmowa', 'NotAllowedError')) },
      configurable: true,
    })
    document.execCommand = ((commandId: string) =>
      commandId !== 'copy') as typeof document.execCommand

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    await screen.findByTestId('admin-key-token')

    await user.click(screen.getByRole('button', { name: 'Kopiuj' }))

    expect(await screen.findByTestId('admin-copy-error')).toHaveTextContent(
      'Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie (Ctrl+C)',
    )
    expect(screen.queryByRole('button', { name: 'Skopiowano' })).toBeNull()
    // Token zaznaczony w dokumencie — użytkownik naciska Ctrl+C (Selection API).
    expect(document.getSelection()?.toString()).toContain('wdk-000000000001-secret')
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/wd/v1/users/:userId/api-keys'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: 'upstream_error', message: 'x' } },
            { status: 500 },
          )
        }
        return HttpResponse.json({ data: { items: [] } })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać danych.',
    )
    expect(screen.queryByText('Brak kluczy API.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('Brak kluczy API.')).toBeInTheDocument()
    expect(calls).toBe(2)
  })
})
