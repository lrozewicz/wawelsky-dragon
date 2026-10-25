/**
 * Kolumna „Włączony” zakładki Pliki (kontrakt WP E3-3b §T5): `Switch` woła `useToggleDocument`,
 * który podmienia `status` optymistycznie i wycofuje zmianę, gdy backend zwróci błąd domenowy.
 * Osobny plik od `DatasetFilesTab.test.tsx` — te testy podmieniają trasę PATCH.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'

afterEach(cleanup)

const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC = fixtureDocument({ id: 'doc-1', name: 'umowa.pdf', status: '1' })

const PATCH_URL = apiUrl('/api/v1/datasets/:datasetId/documents/:documentId')

/** Sam `input` przełącznika — po etykiecie, bo `Switch` z MUI nadaje mu `role="switch"`. */
function enabledSwitch(): HTMLInputElement {
  return screen.getByRole('switch', { name: 'Włączony' })
}

describe('DatasetFilesTab — kolumna „Włączony”', () => {
  it('wyłącza wiersz od razu i wysyła PATCH z enabled:0', async () => {
    const bodies: unknown[] = []
    server.use(
      // Odpowiedź opóźniona — stan po kliknięciu pochodzi z optymistycznej podmiany cache.
      http.patch(PATCH_URL, async ({ request }) => {
        bodies.push(await request.json())
        await delay(100)
        return HttpResponse.json({ code: 0, message: 'success', data: DOC })
      }),
      ...documentsHandlers([DOC]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    expect(await screen.findByTestId('doc-enabled-doc-1')).toBeInTheDocument()
    expect(enabledSwitch()).toBeChecked()

    await user.click(enabledSwitch())

    expect(enabledSwitch()).not.toBeChecked()
    expect(bodies).toEqual([{ enabled: 0 }])
  })

  it('po udanej zmianie lista z serwera zostaje wyłączona', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC], {
        onRequest: (kind, body) => {
          if (kind === 'update') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(enabledSwitch())

    await waitFor(() => expect(enabledSwitch()).not.toBeChecked())
    await waitFor(() => expect(bodies).toEqual([{ enabled: 0 }]))
  })

  it('błąd 102 wycofuje optymistyczne wyłączenie', async () => {
    server.use(
      http.patch(PATCH_URL, async () => {
        await delay(50)
        return HttpResponse.json({ code: 102, message: 'Document not found', data: null })
      }),
      ...documentsHandlers([DOC]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(enabledSwitch())

    await waitFor(() => expect(enabledSwitch()).not.toBeChecked())
    await waitFor(() => expect(enabledSwitch()).toBeChecked())
  })
})
