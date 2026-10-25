/**
 * Dialog importu — krok 2, podsumowanie paczki (kontrakt WP E7-2 §2/§3, brief T6): nazwa
 * wstępnie z `suggested_name` przy `name_taken` (+ ostrzeżenie), 409 `name_conflict` → błąd pod
 * polem z `suggested_name` jako klikalny Chip, model niezgodny → ostrzeżenie o przeliczeniu
 * i wybrany model w ciele `POST /start`, „Anuluj" w kroku 2 → `deleteImport` bez wiersza paska.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  kbDefaultSummary,
  resetKbTransfer,
  setImportPackage,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ImportDialog } from './ImportDialog'

const START_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/start')
const DELETE_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function smallPackage(): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00])], 'paczka.wdkb.zip', {
    type: 'application/zip',
  })
}

async function renderAndUpload(): Promise<{
  onStarted: ReturnType<typeof vi.fn>
  onClose: ReturnType<typeof vi.fn>
}> {
  const onStarted = vi.fn()
  const onClose = vi.fn()
  await renderWithProviders(<ImportDialog onClose={onClose} onStarted={onStarted} />)
  await userEvent.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
  await screen.findByTestId('kb-import-summary')
  return { onStarted, onClose }
}

describe('ImportDialog — krok 2, podsumowanie', () => {
  it('name_taken: nazwa z suggested_name bez ostrzeżenia; wpisanie zajętej nazwy je pokazuje, model zgodny', async () => {
    await renderAndUpload()

    const nameField = screen.getByLabelText('Nazwa')
    expect(nameField).toHaveValue('Rocznik GUS 2024 (import 2026-10-13)')
    // Zaproponowana nazwa jest wolna — ostrzeżenie dotyczy tylko aktualnej wartości pola.
    expect(screen.queryByTestId('kb-import-name-taken')).not.toBeInTheDocument()
    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Rocznik GUS 2024')
    expect(screen.getByTestId('kb-import-name-taken')).toHaveTextContent(
      'Nazwa „Rocznik GUS 2024” jest zajęta',
    )
    await userEvent.type(nameField, ' bis')
    expect(screen.queryByTestId('kb-import-name-taken')).not.toBeInTheDocument()
    expect(
      screen.getByText(/Paczka: Rocznik GUS 2024 · 3 pliki · 7\s+251 chunków · z wektorami/),
    ).toBeInTheDocument()
    expect(screen.getByText(/utworzona .* w Wawelsky Dragon 1\.3\.0/)).toBeInTheDocument()
    expect(screen.getByTestId('kb-import-compatible')).toHaveTextContent('Zgodny z paczką')
    expect(screen.queryByTestId('kb-import-reembed')).not.toBeInTheDocument()
  })

  it('wersja 0.0.0 (DEC-346) jest ukryta; wersja 1.2.0 z backendu widoczna', async () => {
    setImportPackage({ ...kbDefaultSummary(), wd_version: '0.0.0' })
    await renderAndUpload()
    const line = screen.getByText(/utworzona .* w Wawelsky Dragon/)
    expect(line).not.toHaveTextContent('0.0.0')
    cleanup()

    setImportPackage({ ...kbDefaultSummary(), wd_version: '1.2.0' })
    await renderAndUpload()
    expect(screen.getByText(/utworzona .* w Wawelsky Dragon 1\.2\.0/)).toBeInTheDocument()
  })

  it('409 name_conflict: błąd pod polem i Chip propozycji wypełnia nazwę', async () => {
    const user = userEvent.setup()
    // Ziarno MSW: `takenNames` zawiera „Rocznik GUS 2024”, ale podsumowanie mówi, że wolna.
    setImportPackage({ ...kbDefaultSummary(), name_taken: false })
    await renderAndUpload()

    const nameField = screen.getByLabelText('Nazwa')
    expect(nameField).toHaveValue('Rocznik GUS 2024')
    await user.click(screen.getByRole('button', { name: 'Importuj' }))

    expect(await screen.findByText('Nazwa jest już zajęta.', { selector: 'p' })).toBeInTheDocument()
    const proposal = screen.getByText('Rocznik GUS 2024 (import 2026-10-13)')
    await user.click(proposal)
    await waitFor(() =>
      expect(screen.getByLabelText('Nazwa')).toHaveValue('Rocznik GUS 2024 (import 2026-10-13)'),
    )
  })

  it('model niezgodny: ostrzeżenie o przeliczeniu i wybrany model w ciele startu', async () => {
    const user = userEvent.setup()
    const { onStarted } = await renderAndUpload()
    // Pojemnik zamiast `let`: TS nie zawęża pól obiektu zapisywanych w klosure handlera MSW.
    const captured: { body: { name?: string; embedding_model?: string } | null } = { body: null }
    server.use(
      http.post(START_ROUTE, async ({ request }) => {
        captured.body = (await request.json()) as { name: string; embedding_model: string }
        return HttpResponse.json({ data: { task_id: 'task-1', status: 'queued' } }, { status: 202 })
      }),
    )

    await user.click(screen.getByRole('combobox', { name: 'Model embeddingów' }))
    await user.click(screen.getByRole('option', { name: 'bge-m3 (1024)' }))
    expect(screen.getByTestId('kb-import-reembed')).toHaveTextContent(
      /Wszystkie chunki zostaną przeliczone/,
    )
    expect(screen.getByTestId('kb-import-reembed')).toHaveTextContent(/token/)

    await user.click(screen.getByRole('button', { name: 'Importuj' }))

    await waitFor(() =>
      expect(onStarted).toHaveBeenCalledWith(
        { task_id: 'task-1', status: 'queued' },
        'Rocznik GUS 2024 (import 2026-10-13)',
      ),
    )
    expect(captured.body?.embedding_model, 'wybrany model idzie do startu').toBe('bge-m3')
    expect(captured.body?.name).toBe('Rocznik GUS 2024 (import 2026-10-13)')
  })

  it('„Anuluj" w kroku 2 porzuca sesję (deleteImport) i zamyka dialog', async () => {
    const user = userEvent.setup()
    const { onStarted, onClose } = await renderAndUpload()
    let deleted = false
    server.use(
      http.delete(DELETE_ROUTE, () => {
        deleted = true
        return HttpResponse.json({ data: { deleted: true } })
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(deleted, 'MINOR T2: krok 2 kasuje sesję przez DELETE, nie przez cancel()').toBe(true)
    expect(onClose).toHaveBeenCalled()
    expect(onStarted).not.toHaveBeenCalled()
  })
})
