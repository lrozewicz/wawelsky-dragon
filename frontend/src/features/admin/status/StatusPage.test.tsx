/**
 * Status systemu (kontrakt WP E3-6c2 §T6): wartości sond i kolejki, lista workerów z tętnem,
 * chip wersji z healthz, stan błędu per karta (stats 500) oraz odświeżanie statsów co 10 s.
 */

import { act, cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, adminHandlers, makeStats } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { STATUS_REFETCH_MS } from '../constants'
import type { Stats } from '../queries'

import { StatusPage } from './StatusPage'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

/** Stałe czasy fixtures — testy nie zależą od zegara. */
const HEARTBEAT = '2025-01-01T00:00:00Z'

type Worker = Stats['workers']['items'][number]

function makeWorker(overrides: Partial<Worker> = {}): Worker {
  return {
    worker_id: 'worker-1',
    version: '0.1.0',
    started_at: HEARTBEAT,
    heartbeat_at: HEARTBEAT,
    active: true,
    capabilities: null,
    ...overrides,
  }
}

/** Handler statsów zwracający 500 w kopercie błędu wd (kontrakt §0). */
function failingStats(): ReturnType<typeof http.get> {
  return http.get(apiUrl('/api/wd/v1/stats'), () =>
    HttpResponse.json({ error: { code: 'internal_error', message: 'x' } }, { status: 500 }),
  )
}

/** Handler healthz zwracający 500 — trasa bez koperty. */
function failingHealthz(): ReturnType<typeof http.get> {
  return http.get(apiUrl('/api/v1/system/healthz'), () =>
    HttpResponse.json({ error: 'x' }, { status: 500 }),
  )
}

describe('StatusPage', () => {
  it('pokazuje sondy, liczbę workerów i liczby kolejki', async () => {
    server.use(
      ...adminHandlers({
        stats: makeStats({
          database: { ok: true, elapsed_ms: 7 },
          workers: {
            active: 2,
            items: [makeWorker(), makeWorker({ worker_id: 'worker-2', version: '0.2.0' })],
          },
          queue: { queued: 3, running: 1, dead: 0 },
        }),
      }),
    )

    await renderWithProviders(<StatusPage />)

    const page = await screen.findByTestId('admin-status')
    expect(page).toBeInTheDocument()

    const db = within(page).getByTestId('admin-status-db')
    expect(within(db).getByRole('heading', { level: 2, name: 'Baza danych' })).toBeInTheDocument()
    expect(within(db).getByText('OK')).toBeInTheDocument()
    expect(db).toHaveTextContent('7 ms')

    const workers = within(page).getByTestId('admin-status-workers')
    expect(workers).toHaveTextContent('Aktywne workery: 2')
    expect(workers).toHaveTextContent('worker-1')
    expect(workers).toHaveTextContent('worker-2')

    const queue = within(page).getByTestId('admin-status-queue')
    expect(within(queue).getByText('Oczekujące')).toBeInTheDocument()
    expect(within(queue).getByText('3')).toBeInTheDocument()
    expect(within(queue).getByText('1')).toBeInTheDocument()
    expect(within(queue).getByText('0')).toBeInTheDocument()
  })

  it('czas sondy zaokrągla do całkowitych ms (D7 E3-7)', async () => {
    server.use(
      ...adminHandlers({
        stats: makeStats({ database: { ok: true, elapsed_ms: 12.3456 } }),
      }),
    )

    await renderWithProviders(<StatusPage />)

    const db = await screen.findByTestId('admin-status-db')
    // Surowy float nie trafia na ekran — tylko całkowite ms.
    expect(db).toHaveTextContent('12 ms')
    expect(db).not.toHaveTextContent('12.3456')
  })

  it('sonda magazynu z ok=false pokazuje chip Błąd, a baza zostaje OK', async () => {
    server.use(
      ...adminHandlers({
        stats: makeStats({
          database: { ok: true, elapsed_ms: 3 },
          storage: { ok: false, elapsed_ms: 4 },
        }),
      }),
    )

    await renderWithProviders(<StatusPage />)

    const storage = await screen.findByTestId('admin-status-storage')
    expect(within(storage).getByText('Błąd')).toBeInTheDocument()
    expect(within(screen.getByTestId('admin-status-db')).getByText('OK')).toBeInTheDocument()
  })

  it('ostatni sygnał workera formatuje w języku interfejsu, brak sygnału to kreska', async () => {
    server.use(
      ...adminHandlers({
        stats: makeStats({
          workers: {
            active: 1,
            items: [
              makeWorker({ worker_id: 'worker-1', heartbeat_at: HEARTBEAT }),
              makeWorker({ worker_id: 'worker-2', version: null, heartbeat_at: null }),
            ],
          },
        }),
      }),
    )

    await renderWithProviders(<StatusPage />)

    const workers = await screen.findByTestId('admin-status-workers')
    // Surowy ISO nie trafia na ekran — sygnał idzie przez `toLocaleString` języka interfejsu.
    expect(workers).not.toHaveTextContent(HEARTBEAT)
    expect(workers).toHaveTextContent(`Ostatni sygnał: ${new Date(HEARTBEAT).toLocaleString('pl')}`)
    expect(workers).toHaveTextContent('Ostatni sygnał: —')
    // SC-E5-H9-05: etykieta ma podpowiedź „heartbeat usługi”.
    await userEvent.hover(screen.getByText('Ostatni sygnał: —'))
    expect(await screen.findByText('heartbeat usługi')).toBeInTheDocument()
  })

  it('karta wersji pokazuje wersję i chip statusu z healthz', async () => {
    server.use(...adminHandlers({ stats: makeStats({ version: '1.2.3' }) }))

    await renderWithProviders(<StatusPage />)

    const version = await screen.findByTestId('admin-status-version')
    expect(version).toHaveTextContent('1.2.3')
    expect(within(version).getByText('ok')).toBeInTheDocument()
  })

  it('błąd statsów pokazuje cardError w kartach db, storage, workers i queue, ale nie w wersji', async () => {
    // Nadpisania lądują na początku listy MSW (kontrakt MSW: najpierw podany handler wygrywa).
    server.use(failingStats(), ...adminHandlers())

    await renderWithProviders(<StatusPage />)

    const message = 'Nie udało się pobrać statusu.'
    for (const testId of [
      'admin-status-db',
      'admin-status-storage',
      'admin-status-workers',
      'admin-status-queue',
    ]) {
      const card = await screen.findByTestId(testId)
      expect(within(card).getByRole('alert')).toHaveTextContent(message)
    }

    // Healthz odpowiada, więc karta wersji nie jest błędna — pokazuje sam chip.
    const version = screen.getByTestId('admin-status-version')
    expect(within(version).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(version).getByText('ok')).toBeInTheDocument()
  })

  it('niedostępny healthz nie psuje kart ze statsów ani karty wersji', async () => {
    server.use(failingHealthz(), ...adminHandlers({ stats: makeStats({ version: '1.2.3' }) }))

    await renderWithProviders(<StatusPage />)

    expect(within(await screen.findByTestId('admin-status-db')).getByText('OK')).toBeInTheDocument()

    const version = screen.getByTestId('admin-status-version')
    expect(within(version).queryByRole('alert')).not.toBeInTheDocument()
    expect(version).toHaveTextContent('1.2.3')
    expect(within(version).queryByText('ok')).not.toBeInTheDocument()
  })

  it('w trakcie ładowania kart pokazuje Skeleton', async () => {
    // Statsy nigdy nie odpowiadają — karty muszą zostać w stanie ładowania.
    server.use(http.get(apiUrl('/api/wd/v1/stats'), () => new Promise<Response>(() => {})))

    await renderWithProviders(<StatusPage />)

    const db = await screen.findByTestId('admin-status-db')
    expect(db.querySelector('.MuiSkeleton-root')).not.toBeNull()
    expect(within(db).queryByText('OK')).not.toBeInTheDocument()
    expect(
      within(screen.getByTestId('admin-status-workers')).getByRole('heading', { level: 2 }),
    ).toBeInTheDocument()
  })

  it('odświeża statsy po 10 s', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/wd/v1/stats'), () => {
        calls += 1
        return HttpResponse.json({ data: makeStats() })
      }),
    )

    // Fałszywy zegar przed renderem: interwał odświeżania powstaje przy zamontowaniu zapytania.
    vi.useFakeTimers()
    await renderWithProviders(<StatusPage />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(calls).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(STATUS_REFETCH_MS)
    })
    expect(calls).toBe(2)
  })
})
