/**
 * Data wygaśnięcia klucza API (kontrakt WP E3-H2b §C1, K14 §3): puste pole pomija `expires_at`,
 * przyszła data jedzie w ciele jako ISO z „Z", data z przeszłości blokuje wysyłkę i pokazuje
 * `expiresPast`, 400 z API daje Alert, a kolumna „Wygasa" rozróżnia wygasły / datę / bezterminowy.
 * Ostatni przypadek sprawdza sam handler MSW (odrzuca datę bez strefy i datę z przeszłości).
 */

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { adminHandlers, apiUrl, makeWdUser } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { ApiKey } from '../queries'

import { ApiKeysDialog } from './ApiKeysDialog'

beforeEach(() => {
  server.use(...adminHandlers())
})

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

const TS = '2025-01-01T00:00:00Z'
const jan = makeWdUser({ id: 'u-jan', email: 'jan@wd.test' })
const EXPIRES_LABEL = 'Wygasa (opcjonalnie)'
const CREATE_URL = '/api/wd/v1/users/u-jan/api-keys'

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query". */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Handler tworzenia klucza, który zapisuje ciała żądań i oddaje świeżo utworzony klucz. */
function recordCreate(bodies: Array<Record<string, unknown>>, expiresAt: string | null) {
  return http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    bodies.push(body)
    return HttpResponse.json(
      {
        data: {
          id: 'key-new',
          name: body.name ?? null,
          prefix: 'wdk-new',
          created_at: TS,
          last_used_at: null,
          expires_at: expiresAt,
          token: 'wdk-new-secret',
        },
      },
      { status: 201 },
    )
  })
}

/** Lista kluczy z zadanego zbioru — tokenu nie ma w odpowiedzi GET (kontrakt §0). */
function listKeys(items: ApiKey[]) {
  return http.get(apiUrl('/api/wd/v1/users/:userId/api-keys'), () =>
    HttpResponse.json({ data: { items } }),
  )
}

/** Ustawia wartość pola `datetime-local` (userEvent nie pisze po kontrolce daty). */
function setExpires(value: string): void {
  fireEvent.change(screen.getByLabelText(EXPIRES_LABEL), { target: { value } })
}

describe('ApiKeysDialog — data wygaśnięcia', () => {
  it('puste pole nie dodaje klucza expires_at do ciała żądania', async () => {
    const bodies: Array<Record<string, unknown>> = []
    server.use(recordCreate(bodies, null))

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(Object.hasOwn(bodies[0] ?? {}, 'expires_at')).toBe(false)
  })

  it('wpisana przyszła data trafia do ciała jako ISO ze strefą UTC', async () => {
    const bodies: Array<Record<string, unknown>> = []
    server.use(recordCreate(bodies, '2099-12-31T23:59:00.000Z'))

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    setExpires('2099-12-31T23:59')
    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    const sent = bodies[0]?.expires_at
    expect(typeof sent).toBe('string')
    expect(String(sent)).toMatch(/Z$/)
    expect(new Date(String(sent)).getTime()).toBeGreaterThan(Date.now())
  })

  it('data z przeszłości blokuje wysłanie żądania i pokazuje komunikat walidacji', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    setExpires('2020-01-01T00:00')
    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))

    expect(await screen.findByText('Data musi być w przyszłości')).toBeInTheDocument()
    expect(calls.filter((call) => call.startsWith(`POST ${CREATE_URL}`))).toHaveLength(0)
  })

  it('błąd 400 z API pokazuje Alert z komunikatem błędu', async () => {
    server.use(
      http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation_failed',
              message: 'expires_at must be in the future',
            },
          },
          { status: 400 },
        ),
      ),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))

    expect(await screen.findByText('Dane są niepoprawne.')).toBeInTheDocument()
  })

  it('kolumna „Wygasa": przeszłość = Wygasł, przyszłość = data, null = Bezterminowy', async () => {
    server.use(
      listKeys([
        {
          id: 'key-past',
          name: 'przeszły',
          prefix: 'wdk-past',
          created_at: TS,
          last_used_at: null,
          expires_at: '2020-01-01T00:00:00Z',
        },
        {
          id: 'key-future',
          name: 'przyszły',
          prefix: 'wdk-future',
          created_at: TS,
          last_used_at: null,
          expires_at: '2099-06-01T12:00:00Z',
        },
        {
          id: 'key-forever',
          name: 'wieczny',
          prefix: 'wdk-forever',
          created_at: TS,
          last_used_at: null,
          expires_at: null,
        },
      ]),
    )

    await renderWithProviders(<ApiKeysDialog open user={jan} onClose={vi.fn()} />)

    expect(await screen.findByText('Wygasł')).toBeInTheDocument()
    expect(
      screen.getByText(new Date('2099-06-01T12:00:00Z').toLocaleString('pl')),
    ).toBeInTheDocument()
    expect(screen.getByText('Bezterminowy')).toBeInTheDocument()
  })
})

describe('handler MSW kluczy API — expires_at', () => {
  const post = (body: unknown) =>
    fetch(apiUrl(CREATE_URL), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

  it('odrzuca datę bez strefy i datę z przeszłości, zapisuje poprawną', async () => {
    const withoutZone = await post({ name: 'bez-strefy', expires_at: '2099-01-01T00:00:00' })
    expect(withoutZone.status).toBe(400)
    expect((await withoutZone.json()).error.code).toBe('validation_failed')

    const past = await post({ name: 'przeszła', expires_at: '2020-01-01T00:00:00Z' })
    expect(past.status).toBe(400)
    expect((await past.json()).error.code).toBe('validation_failed')

    const unparseable = await post({ name: 'śmieć', expires_at: 'nie-data' })
    expect(unparseable.status).toBe(400)

    const ok = await post({ name: 'dobra', expires_at: '2099-01-01T00:00:00Z' })
    expect(ok.status).toBe(201)
    expect((await ok.json()).data.expires_at).toBe('2099-01-01T00:00:00.000Z')

    const list = await fetch(apiUrl(CREATE_URL))
    const items = (await list.json()).data.items as ApiKey[]
    expect(items).toHaveLength(1)
    expect(items.at(0)?.expires_at).toBe('2099-01-01T00:00:00.000Z')
  })

  it('brak expires_at i null zapisują klucz bezterminowy', async () => {
    const missing = await post({ name: 'brak' })
    expect(missing.status).toBe(201)
    expect((await missing.json()).data.expires_at).toBeNull()

    const explicitNull = await post({ name: 'null', expires_at: null })
    expect(explicitNull.status).toBe(201)
    expect((await explicitNull.json()).data.expires_at).toBeNull()
  })
})
