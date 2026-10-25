/**
 * Biblioteki, historia przebiegów i zdarzenia w dialogu szczegółów (brief T4 p. 4–6, 9):
 * kursor delty i czas ostatniej synchronizacji, doczytywanie stron kursorem, filtr poziomu
 * zdarzeń, ścieżka pliku z nazwą biblioteki oraz błąd pobrania bibliotek.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  integrationsHandlers,
  makeEvent,
  makeIntegration,
  makeRun,
} from '../../../test/msw/handlers'
import type { IntegrationsSeed } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { IntegrationDetailsDialog } from './IntegrationDetailsDialog'
import type { IntegrationDrive, IntegrationEvent, Integration } from './queries'

afterEach(cleanup)

const INTEGRATION_ID = 7
const INTEGRATION_NAME = 'Zespołowa'
const RUN_ID = 5
const TIMESTAMP = '2025-01-01T00:00:00Z'

type User = ReturnType<typeof userEvent.setup>

function DetailsHarness(): JSX.Element {
  const [id, setId] = useState<number | null>(INTEGRATION_ID)
  // Scenariusze tego pliku nie edytują integracji — kolekcja `onEdit` jest tu bezczynna.
  return (
    <IntegrationDetailsDialog integrationId={id} onClose={() => setId(null)} onEdit={() => {}} />
  )
}

/** Uruchamia dialog; `handlers` przed seedem, bo MSW przydziela priorytet wcześniejszym wpisom. */
async function renderDetails(options: {
  seed?: IntegrationsSeed
  handlers?: HttpHandler[]
}): Promise<User> {
  server.use(...(options.handlers ?? []), ...integrationsHandlers(options.seed ?? {}))
  const user = userEvent.setup()
  await renderWithProviders(<DetailsHarness />)
  await screen.findByTestId('integration-details')
  return user
}

const SEED_ONE: IntegrationsSeed = {
  integrations: [makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME })],
}

function drivesHandler(items: IntegrationDrive[]): HttpHandler {
  return http.get(apiUrl('/api/wd/v1/integrations/:integrationId/drives'), () =>
    HttpResponse.json({ data: { items } }),
  )
}

/** Strona zdarzeń z kursorem rosnąco; `pageSize` wymusza „Pokaż więcej" na pierwszej stronie. */
function pagedEventsHandler(rows: IntegrationEvent[], pageSize: number): HttpHandler {
  return http.get(apiUrl('/api/wd/v1/runs/:runId/events'), ({ request }) => {
    const after = new URL(request.url).searchParams.get('after_id')
    const cursor = after === null ? 0 : Number(after)
    const page = rows.filter((row) => row.id > cursor).slice(0, pageSize)
    const last = page.at(-1)
    return HttpResponse.json({
      data: {
        items: page,
        next_after_id: page.length === pageSize && last !== undefined ? last.id : null,
      },
    })
  })
}

describe('IntegrationDetailsDialog — biblioteki', () => {
  it('pokazuje nazwę, kursor delty i czas ostatniej synchronizacji', async () => {
    await renderDetails({
      seed: SEED_ONE,
      handlers: [
        drivesHandler([
          {
            drive_id: 'd1',
            drive_name: 'Dokumenty',
            has_delta: true,
            last_sync_at: TIMESTAMP,
            discovered_at: null,
          },
          {
            drive_id: 'd2',
            drive_name: 'Archiwum',
            has_delta: false,
            last_sync_at: null,
            discovered_at: null,
          },
        ]),
      ],
    })

    const dialog = await screen.findByTestId('integration-details')
    expect(await within(dialog).findByText('Dokumenty')).toBeInTheDocument()
    expect(within(dialog).getByText('Archiwum')).toBeInTheDocument()
    expect(within(dialog).getAllByText('Kursor delty')).toHaveLength(1)
    expect(
      within(dialog).getByText('Ostatnia synchronizacja: 1.01.2025, 00:00:00'),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Ostatnia synchronizacja: —')).toBeInTheDocument()
  })

  it('błąd pobrania bibliotek pokazuje komunikat', async () => {
    await renderDetails({
      seed: SEED_ONE,
      handlers: [
        http.get(apiUrl('/api/wd/v1/integrations/:integrationId/drives'), () =>
          HttpResponse.json(
            { error: { code: 'upstream_error', message: 'Graph nie odpowiada' } },
            { status: 502 },
          ),
        ),
      ],
    })

    expect(await screen.findByText('Błąd usługi zewnętrznej.')).toBeInTheDocument()
  })
})

describe('IntegrationDetailsDialog — historia przebiegów', () => {
  it('„Pokaż więcej" doczytuje kolejną stronę kursorem', async () => {
    // 21 przebiegów przy stronie 20: pierwsza strona kończy się na id 2, kursor to `next_after_id`.
    const runs = Array.from({ length: 21 }, (_, index) => makeRun({ id: 21 - index }))
    const user = await renderDetails({ seed: { ...SEED_ONE, runs: { [INTEGRATION_ID]: runs } } })

    expect(await screen.findByTestId('integration-run-21')).toBeInTheDocument()
    expect(screen.getByTestId('integration-run-2')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-run-1')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('integration-runs-more'))

    expect(await screen.findByTestId('integration-run-1')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('integration-runs-more')).not.toBeInTheDocument()
    })
  })

  it('błąd doładowania strony pokazuje komunikat, a przycisk zostaje', async () => {
    // Pierwsza strona przychodzi z kursorem, druga pada (502) — użytkownik może spróbować ponownie.
    const handler = http.get(
      apiUrl('/api/wd/v1/integrations/:integrationId/runs'),
      ({ request }) => {
        const after = new URL(request.url).searchParams.get('after_id')
        if (after !== null) {
          return HttpResponse.json(
            { error: { code: 'upstream_error', message: 'x' } },
            { status: 502 },
          )
        }
        return HttpResponse.json({
          data: { items: [makeRun({ id: 3 }), makeRun({ id: 2 })], next_after_id: 2 },
        })
      },
    )
    const user = await renderDetails({ seed: SEED_ONE, handlers: [handler] })

    await user.click(await screen.findByTestId('integration-runs-more'))

    expect(await screen.findByText('Błąd usługi zewnętrznej.')).toBeInTheDocument()
    expect(screen.getByTestId('integration-runs-more')).toBeInTheDocument()
  })
})

describe('IntegrationDetailsDialog — zdarzenia przebiegu', () => {
  const EVENTS: IntegrationEvent[] = [
    makeEvent({ id: 1, run_id: RUN_ID, level: 'info', message: 'Rozpoczęto przebieg' }),
    makeEvent({
      id: 2,
      run_id: RUN_ID,
      level: 'warn',
      message: 'Pominięto duży plik',
      file_path: '/Dokumenty/duzy.pdf',
      drive_name: 'Dokumenty',
    }),
    // Schemat API zna `warn`, kontrakt starsze `warning` — oba pokazujemy jako ostrzeżenie.
    makeEvent({ id: 3, run_id: RUN_ID, level: 'warning', message: 'Delta wygasła' }),
  ]

  const SEED_WITH_RUN: IntegrationsSeed = {
    integrations: [SEED_ONE.integrations?.[0] as Integration],
    runs: { [INTEGRATION_ID]: [makeRun({ id: RUN_ID, status: 'success', added: 2 })] },
    events: { [RUN_ID]: EVENTS },
  }

  it('klik przebiegu pokazuje jego zdarzenia ze ścieżką pliku i biblioteką', async () => {
    const user = await renderDetails({ seed: SEED_WITH_RUN })

    await user.click(await screen.findByTestId(`integration-run-${RUN_ID}`))

    expect(await screen.findByText('Zdarzenia przebiegu')).toBeInTheDocument()
    expect(await screen.findByText('Rozpoczęto przebieg')).toBeInTheDocument()
    expect(screen.getByText('Informacja')).toBeInTheDocument()
    // `warn` i starszy `warning` oba jako ostrzeżenie (brief p. 6).
    expect(screen.getAllByText('Ostrzeżenie')).toHaveLength(2)
    expect(screen.getByText('/Dokumenty/duzy.pdf · Dokumenty')).toBeInTheDocument()
  })

  it('filtr poziomu zawęża listę zdarzeń', async () => {
    const user = await renderDetails({ seed: SEED_WITH_RUN })

    await user.click(await screen.findByTestId(`integration-run-${RUN_ID}`))
    await screen.findByText('Rozpoczęto przebieg')

    await user.click(screen.getByRole('combobox', { name: 'Poziom' }))
    await user.click(await screen.findByRole('option', { name: 'Ostrzeżenie' }))

    await waitFor(() => {
      expect(screen.queryByText('Rozpoczęto przebieg')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Pominięto duży plik')).toBeInTheDocument()
  })

  it('„Pokaż więcej" doczytuje zdarzenia kursorem', async () => {
    const many = [
      makeEvent({ id: 1, run_id: RUN_ID, level: 'info', message: 'Pierwsze' }),
      makeEvent({ id: 2, run_id: RUN_ID, level: 'info', message: 'Drugie' }),
      makeEvent({ id: 3, run_id: RUN_ID, level: 'info', message: 'Trzecie' }),
    ]
    const user = await renderDetails({
      seed: {
        integrations: [makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME })],
        runs: { [INTEGRATION_ID]: [makeRun({ id: RUN_ID })] },
      },
      handlers: [pagedEventsHandler(many, 2)],
    })

    await user.click(await screen.findByTestId(`integration-run-${RUN_ID}`))
    expect(await screen.findByText('Pierwsze')).toBeInTheDocument()
    expect(screen.queryByText('Trzecie')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('integration-events-more'))

    expect(await screen.findByText('Trzecie')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('integration-events-more')).not.toBeInTheDocument()
    })
  })
})
