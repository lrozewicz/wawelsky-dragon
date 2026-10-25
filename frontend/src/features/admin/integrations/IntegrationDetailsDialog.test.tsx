/**
 * Dialog szczegółów integracji (brief T4 p. 1–3, 7, 9): nazwa i edycja, stan z licznikami
 * i czasami, pusta historia, synchronizacja z potwierdzeniem (przyrostowa i pełna), blokada
 * synchronizacji i anulowanie przy aktywnym przebiegu, błąd 409 oraz usunięcie z potwierdzeniem.
 * Wysyłkę żądań dowodzimy zdarzeniami cyklu życia MSW — nie podmieniamy handlerów.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { initI18n } from '../../../i18n'
import { apiUrl, integrationsHandlers, makeIntegration, makeRun } from '../../../test/msw/handlers'
import type { IntegrationsSeed } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { IntegrationDetailsDialog } from './IntegrationDetailsDialog'
import { INTEGRATION_POLL_MS } from './queries'
import type { Integration } from './queries'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
  vi.useRealTimers()
})

const INTEGRATION_ID = 7
const INTEGRATION_NAME = 'Zespołowa'
const RUN_STARTED = '2025-01-01T00:00:00Z'
const RUN_FINISHED = '2025-01-01T00:05:00Z'

type User = ReturnType<typeof userEvent.setup>

/** Rodzic trzymający `integrationId` — po usunięciu dialog znika z drzewa. */
function DetailsHarness(props: { onEdit: (integration: Integration) => void }): JSX.Element {
  const [id, setId] = useState<number | null>(INTEGRATION_ID)
  return (
    <IntegrationDetailsDialog
      integrationId={id}
      onClose={() => setId(null)}
      onEdit={props.onEdit}
    />
  )
}

/** Metoda i URL każdego przechwyconego żądania — dowód, że mutacja naprawdę wyszła. */
function recordRequests(): string[] {
  const seen: string[] = []
  server.events.on('request:start', ({ request }) => {
    seen.push(`${request.method} ${request.url}`)
  })
  return seen
}

/** Dialog potwierdzenia po tytule — oba (szczegóły i potwierdzenie) mają `role="dialog"`. */
function dialogByTitle(title: string): HTMLElement {
  const node = screen.getByText(title).closest('[role="dialog"]')
  if (node === null) throw new Error(`Brak dialogu o tytule: ${title}`)
  return node as HTMLElement
}

/** Uruchamia dialog na seedzie MSW i zwraca `user` oraz listę żądań. */
async function renderDetails(options: {
  seed?: IntegrationsSeed
  handlers?: HttpHandler[]
  onEdit?: (integration: Integration) => void
}): Promise<{ user: User; requests: string[] }> {
  server.use(...(options.handlers ?? []), ...integrationsHandlers(options.seed ?? {}))
  const requests = recordRequests()
  const user = userEvent.setup()
  await renderWithProviders(<DetailsHarness onEdit={options.onEdit ?? (() => {})} />)
  await screen.findByTestId('integration-details')
  return { user, requests }
}

/** Seed jednej integracji (bez przebiegów), wspólny dla większości scenariuszy. */
const SEED_ONE: IntegrationsSeed = {
  integrations: [makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME })],
}

describe('IntegrationDetailsDialog', () => {
  it('pokazuje nazwę, chip statusu, liczniki i czasy ostatniego przebiegu', async () => {
    await renderDetails({
      seed: {
        integrations: [makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME })],
        runs: {
          [INTEGRATION_ID]: [
            makeRun({
              id: 3,
              status: 'partial',
              added: 5,
              updated: 2,
              deleted: 1,
              failed: 4,
              started_at: RUN_STARTED,
              finished_at: RUN_FINISHED,
            }),
          ],
        },
      },
    })

    const dialog = await screen.findByTestId('integration-details')
    expect(await within(dialog).findByText(INTEGRATION_NAME)).toBeInTheDocument()
    // Ten sam przebieg widać w sekcji stanu i w wierszu historii — stąd dwa chipy.
    expect(within(dialog).getAllByText('Częściowo')).toHaveLength(2)
    expect(within(dialog).getByText('Dodane: 5')).toBeInTheDocument()
    expect(within(dialog).getByText('Zmienione: 2')).toBeInTheDocument()
    expect(within(dialog).getByText('Usunięte: 1')).toBeInTheDocument()
    expect(within(dialog).getByText('Błędy: 4')).toBeInTheDocument()
    expect(within(dialog).getByText(/^Start: /)).toBeInTheDocument()
    expect(within(dialog).getByText(/^Koniec: /)).toBeInTheDocument()
  })

  it('bez przebiegów pokazuje „Nigdy", puste biblioteki i pustą historię', async () => {
    await renderDetails({ seed: SEED_ONE })

    const dialog = await screen.findByTestId('integration-details')
    expect(await within(dialog).findByText('Nigdy')).toBeInTheDocument()
    expect(within(dialog).getByText('Brak bibliotek — uruchom synchronizację.')).toBeInTheDocument()
    expect(within(dialog).getByText('Brak przebiegów')).toBeInTheDocument()
    expect(
      within(dialog).getByText('Wybierz przebieg, żeby zobaczyć jego zdarzenia.'),
    ).toBeInTheDocument()
  })

  it('w trakcie ładowania integracji pokazuje tytuł zastępczy, nie surowy klucz', async () => {
    await renderDetails({
      seed: SEED_ONE,
      // Odpowiedź na szczegóły integracji nigdy nie przychodzi — nagłówek ma zostać na fallbacku.
      handlers: [http.get(apiUrl('/api/wd/v1/integrations/:id'), () => delay('infinite'))],
    })

    expect(await screen.findByText('Szczegóły integracji')).toBeInTheDocument()
  })

  it('przycisk „Edytuj" przekazuje integrację do onEdit', async () => {
    const edited: Integration[] = []
    const { user } = await renderDetails({
      seed: SEED_ONE,
      onEdit: (integration) => edited.push(integration),
    })

    await screen.findByText(INTEGRATION_NAME)
    await user.click(screen.getByRole('button', { name: 'Edytuj' }))

    expect(edited).toHaveLength(1)
    expect(edited[0]?.id).toBe(INTEGRATION_ID)
  })

  it('synchronizacja przyrostowa wysyła full=false i po starcie blokuje przycisk', async () => {
    const { user, requests } = await renderDetails({ seed: SEED_ONE })

    // Checkbox pełnej synchronizacji żyje wyłącznie w dialogu potwierdzenia.
    expect(screen.queryByRole('checkbox', { name: 'Pełna synchronizacja' })).not.toBeInTheDocument()
    await user.click(await screen.findByTestId('integration-sync'))
    const confirm = dialogByTitle('Uruchomić synchronizację?')
    expect(
      within(confirm).getByRole('checkbox', { name: 'Pełna synchronizacja' }),
    ).not.toBeChecked()
    await user.click(within(confirm).getByRole('button', { name: 'Synchronizuj' }))

    await waitFor(() => {
      expect(requests.some((call) => call.includes('/sync') && call.includes('full=false'))).toBe(
        true,
      )
    })
    // Mock po synchronizacji ustawia `is_running` — przycisk blokuje się, a anulowanie się pojawia.
    expect(await screen.findByTestId('integration-cancel')).toBeInTheDocument()
    expect(screen.getByTestId('integration-sync')).toBeDisabled()
  })

  it('zaznaczona w dialogu „Pełna synchronizacja" wysyła full=true', async () => {
    const { user, requests } = await renderDetails({ seed: SEED_ONE })

    await user.click(await screen.findByTestId('integration-sync'))
    const confirm = dialogByTitle('Uruchomić synchronizację?')
    // Checkbox pełnej synchronizacji należy do dialogu potwierdzenia, nie do paska akcji.
    const fullSync = within(confirm).getByRole('checkbox', { name: 'Pełna synchronizacja' })
    await user.click(fullSync)
    expect(fullSync).toBeChecked()
    await user.click(within(confirm).getByRole('button', { name: 'Synchronizuj' }))

    await waitFor(() => {
      expect(requests.some((call) => call.includes('/sync') && call.includes('full=true'))).toBe(
        true,
      )
    })
  })

  it('anulowanie potwierdzone wysyła cancel', async () => {
    const { user, requests } = await renderDetails({
      seed: {
        integrations: [
          makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME, is_running: true }),
        ],
        runs: { [INTEGRATION_ID]: [makeRun({ id: 1, status: 'running' })] },
      },
    })

    await user.click(await screen.findByTestId('integration-cancel'))
    const confirm = dialogByTitle('Anulować przebieg?')
    await user.click(within(confirm).getByRole('button', { name: 'Anuluj przebieg' }))

    await waitFor(() => {
      expect(requests.some((call) => call.includes('/cancel'))).toBe(true)
    })
  })

  it('konflikt 409 przy synchronizacji pokazuje komunikat błędu', async () => {
    const { user } = await renderDetails({ seed: SEED_ONE })

    server.use(
      http.post(apiUrl('/api/wd/v1/integrations/:integrationId/sync'), () =>
        HttpResponse.json(
          { error: { code: 'conflict', message: 'Przebieg już trwa' } },
          { status: 409 },
        ),
      ),
    )

    await user.click(await screen.findByTestId('integration-sync'))
    const confirm = dialogByTitle('Uruchomić synchronizację?')
    await user.click(within(confirm).getByRole('button', { name: 'Synchronizuj' }))

    expect(await screen.findByText(/Operacja niedozwolona: konflikt/)).toBeInTheDocument()
  })

  it('usunięcie z potwierdzeniem wysyła DELETE i zamyka dialog', async () => {
    const { user, requests } = await renderDetails({ seed: SEED_ONE })

    await screen.findByText(INTEGRATION_NAME)
    await user.click(screen.getByTestId('integration-delete'))

    const confirm = dialogByTitle('Usunąć integrację?')
    expect(within(confirm).getByText(/Dokumenty w datasecie zostają/)).toBeInTheDocument()
    await user.click(within(confirm).getByRole('button', { name: 'Usuń integrację' }))

    await waitFor(() => {
      expect(requests.some((call) => call.startsWith('DELETE'))).toBe(true)
    })
    await waitFor(() => {
      expect(screen.queryByTestId('integration-details')).not.toBeInTheDocument()
    })
  })
})

describe('IntegrationDetailsDialog — polling statusu', () => {
  it('odpytuje status co 3 s, dopóki przebieg trwa', async () => {
    const seen: string[] = []
    server.use(
      ...integrationsHandlers({
        integrations: [
          makeIntegration({ id: INTEGRATION_ID, name: INTEGRATION_NAME, is_running: true }),
        ],
        runs: { [INTEGRATION_ID]: [makeRun({ id: 1, status: 'running' })] },
      }),
    )
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/status')) seen.push(request.url)
    })

    // Tłumaczenia ładujemy przed fałszywym zegarem — inaczej dynamiczny `import()` czeka na timer.
    await initI18n('pl')
    vi.useFakeTimers()
    await renderWithProviders(<DetailsHarness onEdit={() => {}} />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(seen).toHaveLength(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTEGRATION_POLL_MS)
    })
    expect(seen).toHaveLength(2)
  })
})
