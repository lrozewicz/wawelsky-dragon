/**
 * Usunięcie integracji z dialogu szczegółów (brief T6): po udanym DELETE zamontowany jeszcze
 * dialog nie może dociągać tras usuniętego zasobu (szczegóły, status, biblioteki, przebiegi) —
 * inaczej Chromium loguje cztery 404 (WNIOSEK E4-3d). Żądania GET liczymy w handlerach
 * `server.use`, uzbrojonych od chwili, gdy przyszedł DELETE.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, makeIntegration } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { IntegrationDetailsDialog } from './IntegrationDetailsDialog'
import type { Integration } from './queries'

afterEach(cleanup)

const INTEGRATION_ID = 7
const INTEGRATION_NAME = 'Zespołowa'

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

/** Dialog potwierdzenia po tytule — oba (szczegóły i potwierdzenie) mają `role="dialog"`. */
function dialogByTitle(title: string): HTMLElement {
  const node = screen.getByText(title).closest('[role="dialog"]')
  if (node === null) throw new Error(`Brak dialogu o tytule: ${title}`)
  return node as HTMLElement
}

/**
 * Handlery tras integracji `id` z licznikami GET-ów. Przed DELETE odpowiadają poprawnie (dialog
 * się zapełnia), po DELETE każdy GET trafia do `afterDelete` i dostaje 404, jak backend.
 */
function deletionHandlers(id: number): {
  handlers: HttpHandler[]
  beforeDelete: string[]
  afterDelete: string[]
} {
  let deleted = false
  const beforeDelete: string[] = []
  const afterDelete: string[] = []
  const record = (url: string, body: unknown) => {
    if (deleted) {
      afterDelete.push(url)
      return HttpResponse.json(
        { error: { code: 'not_found', message: 'Nie ma takiej integracji' } },
        { status: 404 },
      )
    }
    beforeDelete.push(url)
    return HttpResponse.json({ data: body })
  }

  const handlers: HttpHandler[] = [
    http.delete(apiUrl('/api/wd/v1/integrations/:id'), () => {
      deleted = true
      return new HttpResponse(null, { status: 204 })
    }),
    http.get(apiUrl('/api/wd/v1/integrations/:id'), ({ request }) =>
      record(request.url, makeIntegration({ id, name: INTEGRATION_NAME })),
    ),
    http.get(apiUrl('/api/wd/v1/integrations/:id/status'), ({ request }) =>
      record(request.url, { id, is_running: false, last_sync_status: null, latest_run: null }),
    ),
    http.get(apiUrl('/api/wd/v1/integrations/:id/drives'), ({ request }) =>
      record(request.url, { items: [] }),
    ),
    http.get(apiUrl('/api/wd/v1/integrations/:id/runs'), ({ request }) =>
      record(request.url, { items: [], next_after_id: null }),
    ),
  ]
  return { handlers, beforeDelete, afterDelete }
}

describe('IntegrationDetailsDialog — usunięcie', () => {
  it('po usunięciu nie odpytuje już tras usuniętego zasobu', async () => {
    const { handlers, beforeDelete, afterDelete } = deletionHandlers(INTEGRATION_ID)
    // Handlery liczące muszą przejąć trasy `:id` od domyślnych — rejestrujemy je pierwsze.
    server.use(...handlers)
    const user = userEvent.setup()
    await renderWithProviders(<DetailsHarness onEdit={() => {}} />)

    await screen.findByText(INTEGRATION_NAME)
    // Kontrola dodatnia: licznik działa, bo karta najpierw naprawdę odczytała szczegóły.
    expect(beforeDelete, 'GET-y przed usunięciem').not.toEqual([])

    await user.click(screen.getByTestId('integration-delete'))
    const confirm = dialogByTitle('Usunąć integrację?')
    await user.click(within(confirm).getByRole('button', { name: 'Usuń integrację' }))

    await waitFor(() => {
      expect(screen.queryByTestId('integration-details')).not.toBeInTheDocument()
    })
    // Polling statusu (co 3 s) nie może już dogonić zamkniętego dialogu.
    expect(afterDelete, 'GET-y tras usuniętej integracji po DELETE').toEqual([])
  })
})
