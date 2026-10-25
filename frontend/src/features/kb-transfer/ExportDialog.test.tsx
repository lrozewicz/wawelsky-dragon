import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, kbDefaultPreview, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ExportDialog } from './ExportDialog'
import type { TaskRef } from './types'

beforeEach(() => {
  resetKbTransfer()
})

afterEach(cleanup)

/**
 * Rodzic-atrapa: dialog zamontowany, dopóki nie zadziała `onClose` (jak w `DatasetsPage`,
 * gdzie `exportTarget !== null` steruje montowaniem). Zwraca uchwyty wywołań zwrotnych.
 */
function renderHarness(
  dataset: { id: string; name: string } = { id: 'd1', name: 'Rocznik GUS 2024' },
) {
  const state = { closed: 0, started: [] as TaskRef[], existing: [] as string[] }
  function Harness() {
    const [open, setOpen] = useState(true)
    return open ? (
      <ExportDialog
        dataset={dataset}
        onClose={() => {
          state.closed += 1
          setOpen(false)
        }}
        onStarted={(ref) => {
          state.started.push(ref)
        }}
        onExisting={(taskId) => {
          state.existing.push(taskId)
        }}
      />
    ) : null
  }
  void renderWithProviders(<Harness />, { routes: ['/datasets'] })
  return state
}

/** Szacunek „Do paczki trafią: …” — jeden element w dialogu. */
function summary() {
  return within(screen.getByRole('dialog')).getByTestId('kb-export-summary')
}

/** Przełącznik wektorów — MUI v9 nadaje inputowi `role="switch"` (CONTRACT §7: switch/checkbox). */
function vectorsSwitch() {
  return screen.getByRole('switch', { name: 'Dołącz wektory' })
}

describe('ExportDialog', () => {
  it('pokazuje tytuł z nazwą, szacunek (odmiana PL), przełącznik włączony i notę o kluczach', async () => {
    renderHarness()

    const dialog = await screen.findByRole('dialog', { name: 'Eksportuj „Rocznik GUS 2024”' })
    // Ziarno MSW: 3 dokumenty, 7 251 chunków, 77 594 624 B = 74 MB z wektorami.
    await waitFor(() => {
      expect(summary().textContent).toMatch(
        /^Do paczki trafią: 3 pliki · 7\s*251 chunków · ok\.\s*74\s*MB$/,
      )
    })
    expect(vectorsSwitch()).toBeChecked()
    expect(
      within(dialog).getByText(
        'Paczka nie zawiera kluczy, użytkowników, czatów ani ustawień modeli.',
      ),
    ).toBeInTheDocument()
    // Opis modelu embeddingów z ziarna: text-embedding-3-small (1536) i rozmiar bez wektorów.
    expect(within(dialog).getByText(/text-embedding-3-small, 1536/)).toBeInTheDocument()
    expect(within(dialog).getByText(/ok\.\s*30\s*MB/)).toBeInTheDocument()
  })

  it('przełączenie „Dołącz wektory” zmienia szacunek na mniejszy (SC-E7-2-01 krok 3)', async () => {
    const user = userEvent.setup()
    renderHarness()

    await waitFor(() => {
      expect(summary().textContent).toMatch(/ok\.\s*74\s*MB/)
    })
    await user.click(vectorsSwitch())
    await waitFor(() => {
      expect(summary().textContent).toMatch(/ok\.\s*30\s*MB/)
    })
    expect(vectorsSwitch()).not.toBeChecked()
  })

  it('szacunek ponad limit: „Eksportuj” nieaktywny + komunikat WD_EXPORT_MAX_BYTES', async () => {
    // Ziarno: max_bytes 2 GiB; paczka z wektorami 3 GiB — ponad limit.
    server.use(
      ...kbPreviewHandlers({ ...kbDefaultPreview(), estimated_bytes_with_vectors: 3 * 1024 ** 3 }),
    )

    renderHarness()

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => {
      expect(
        within(dialog).getByText('Paczka przekroczy limit 2 GB (WD_EXPORT_MAX_BYTES)'),
      ).toBeInTheDocument()
    })
    expect(within(dialog).getByRole('button', { name: 'Eksportuj' })).toBeDisabled()
  })

  it('wysyła `include_vectors` zgodnie z przełącznikiem i oddaje onStarted + zamknięcie', async () => {
    const user = userEvent.setup()
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ data: { task_id: 'task-9', status: 'queued' } }, { status: 202 })
      }),
    )
    const state = renderHarness()

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByTestId('kb-export-summary')).toBeInTheDocument()
    })
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))
    await waitFor(() => {
      expect(state.started).toEqual([{ task_id: 'task-9', status: 'queued' }])
    })
    expect(bodies).toEqual([{ include_vectors: true }])
    expect(state.closed).toBe(1)
    // Rodzic odmontowuje dialog po `onClose` — jak w `DatasetsPage`.
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('`include_vectors: false` po wyłączeniu przełącznika', async () => {
    const user = userEvent.setup()
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({ data: { task_id: 'task-9', status: 'queued' } }, { status: 202 })
      }),
    )
    const state = renderHarness()

    const dialog = await screen.findByRole('dialog')
    await user.click(await screen.findByRole('switch', { name: 'Dołącz wektory' }))
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))
    await waitFor(() => {
      expect(state.started).toHaveLength(1)
    })
    expect(bodies).toEqual([{ include_vectors: false }])
  })

  it('409 `export_in_progress`: zamyka dialog i oddaje task_id przez onExisting', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), () =>
        HttpResponse.json(
          {
            error: {
              code: 'export_in_progress',
              message: 'Eksport tej bazy wiedzy już trwa.',
              details: { task_id: 'task-running-1' },
            },
          },
          { status: 409 },
        ),
      ),
    )
    const state = renderHarness()

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByTestId('kb-export-summary')).toBeInTheDocument()
    })
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))
    await waitFor(() => {
      expect(state.existing).toEqual(['task-running-1'])
    })
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('inny błąd startu zostaje w dialogu jako Alert z kbErrorMessageKey', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(apiUrl('/api/wd/v1/datasets/d1/export'), () =>
        HttpResponse.json(
          { error: { code: 'forbidden', message: 'Brak uprawnień.' } },
          { status: 403 },
        ),
      ),
    )
    const state = renderHarness()

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByTestId('kb-export-summary')).toBeInTheDocument()
    })
    await user.click(within(dialog).getByRole('button', { name: 'Eksportuj' }))
    await waitFor(() => {
      expect(within(dialog).getByText('Brak uprawnień do tej operacji.')).toBeInTheDocument()
    })
    expect(state.existing).toEqual([])
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('błąd podglądu: Alert + „Ponów” powtarza żądanie i pokazuje szacunek', async () => {
    const user = userEvent.setup()
    let calls = 0
    server.use(
      http.get(apiUrl('/api/wd/v1/datasets/d1/export/preview'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: 'not_found', message: 'Nie znaleziono bazy wiedzy.' } },
            { status: 404 },
          )
        }
        return HttpResponse.json({ data: kbDefaultPreview() })
      }),
    )
    renderHarness()

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByText('Nie znaleziono zasobu.')).toBeInTheDocument()
    })
    await user.click(within(dialog).getByRole('button', { name: 'Ponów' }))
    await waitFor(() => {
      expect(within(dialog).getByTestId('kb-export-summary').textContent).toMatch(/ok\.\s*74\s*MB/)
    })
    expect(calls).toBe(2)
  })

  it('ładowanie podglądu pokazuje szkielet zamiast treści (08 §7.15 U5)', async () => {
    server.use(
      http.get(apiUrl('/api/wd/v1/datasets/d1/export/preview'), () => new Promise(() => undefined)),
    )
    renderHarness()

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByTestId('kb-export-skeleton')).toBeInTheDocument()
    expect(within(dialog).queryByTestId('kb-export-summary')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Eksportuj' })).toBeDisabled()
  })
})

/** Nadpisuje podgląd eksportu (trasa 1) wybraną wartością. */
function kbPreviewHandlers(preview: ReturnType<typeof kbDefaultPreview>) {
  return [
    http.get(apiUrl('/api/wd/v1/datasets/d1/export/preview'), () =>
      HttpResponse.json({ data: preview }),
    ),
  ]
}
