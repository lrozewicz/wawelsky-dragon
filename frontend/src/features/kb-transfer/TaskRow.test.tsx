/**
 * Stany wiersza paska zadań (08 §7.15 (b); SC-E7-2-01 kroki 4–6, SC-E7-2-04 krok 5):
 * „W kolejce” przed pierwszym odpytaniem, etap z licznikiem i procentem, „Gotowe” eksportu
 * (Pobierz, Kopiuj link) i importu (Otwórz), błąd z rozwijanymi szczegółami, „Anulowano”;
 * Stop → POST /tasks/{id}/stop, ✕ usuwa wiersz, kopiowanie bezwzględnego linku (odmowa
 * schowka → komunikat błędu), „Pobierz” = zwykły link z `download` (strumieniowanie przez
 * przeglądarkę, bez blobu w pamięci strony), a po `expires_at` nieaktywny z komunikatem
 * kbTransfer.error.export_expired.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { copyToClipboard } from '../settings/api/copyToClipboard'

import { TaskRow } from './TaskRow'
import type { StoredKbTask, WdTask } from './types'

vi.mock('../settings/api/copyToClipboard', () => ({
  copyToClipboard: vi.fn(async () => true),
}))

const DOWNLOAD_URL = '/api/wd/v1/exports/task-1/download?exp=4102444800&sig=task-1'
const EXPIRES_AT = 4_102_444_800_000 // ms; „link ważny do” — formatDateTime w jsdom zależny od TZ

function wdTask(overrides: Partial<WdTask> = {}): WdTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    dataset_id: 'd1',
    status: 'running',
    stage: 'chunks',
    done: 3000,
    total: 7251,
    progress: 0.41,
    message: 'Chunki 3000/7251',
    error: null,
    created_at: Date.now(),
    finished_at: null,
    result: null,
    ...overrides,
  }
}

function storedRow(overrides: Partial<StoredKbTask> = {}): StoredKbTask {
  return {
    task_id: 'task-1',
    kind: 'export',
    label: 'Rocznik GUS 2024',
    dataset_id: 'd1',
    added_at: Date.now(),
    last: wdTask({
      status: 'done',
      result: {
        download_url: DOWNLOAD_URL,
        expires_at: EXPIRES_AT,
        size_bytes: 77_594_624,
        file_name: 'rocznik-gus.wdkb.zip',
      },
    }),
    ...overrides,
  }
}

const onRemove = vi.fn()

async function renderRow(row: StoredKbTask, highlighted = false) {
  return renderWithProviders(<TaskRow row={row} highlighted={highlighted} onRemove={onRemove} />, {
    routes: ['/datasets', '/dataset/files/$id'],
  })
}

function row(): HTMLElement {
  return screen.getByTestId('kb-task-row')
}

beforeEach(() => {
  vi.mocked(copyToClipboard).mockClear()
  onRemove.mockClear()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('TaskRow — stany wiersza', () => {
  it('świeży wiersz (last: null) pokazuje „W kolejce” i Stop', async () => {
    await renderRow(storedRow({ last: null }))

    expect(row()).toHaveAttribute('data-task-status', 'queued')
    expect(screen.getByText('W kolejce')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pobierz' })).not.toBeInTheDocument()
  })

  it('w trakcie: etap, licznik done/total z grupowaniem, procent; ✕ nieobecny', async () => {
    await renderRow(storedRow({ last: wdTask() }))

    expect(row()).toHaveAttribute('data-task-status', 'running')
    // Testing Library normalizuje twarde spacje do zwykłych — bezpośrednie porównanie NBSP
    // robi test `format.test.ts`.
    expect(screen.getByText(/Chunki 3 000\/7 251/)).toBeInTheDocument()
    expect(screen.getByText('41%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zamknij' })).not.toBeInTheDocument()
  })

  it('eksport gotowy: rozmiar, termin linku, Pobierz, Kopiuj link i ✕', async () => {
    await renderRow(storedRow())

    expect(row()).toHaveAttribute('data-task-status', 'done')
    expect(screen.getByText(/Gotowe · 74 MB · link ważny do/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pobierz' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Kopiuj link' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zamknij' })).toBeInTheDocument()
  })

  it('import gotowy: „Gotowe — N plików, M chunków”, Otwórz prowadzi do bazy', async () => {
    const { router } = await renderRow(
      storedRow({
        kind: 'import',
        last: wdTask({
          kind: 'import',
          status: 'done',
          stage: null,
          progress: 1,
          result: {
            dataset_id: 'ds-9',
            dataset_name: 'Rocznik GUS 2024',
            documents: 2,
            chunks: 7251,
            reembedded: false,
          },
        }),
      }),
    )

    expect(screen.getByText(/Gotowe — 2 pliki, 7 251 chunków/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Otwórz' }))
    expect(router.state.location.pathname).toBe('/dataset/files/ds-9')
  })

  it('błąd: „Błąd: <tekst wg kodu>”, Szczegóły rozwija komunikat serwera', async () => {
    const user = userEvent.setup()
    await renderRow(
      storedRow({
        last: wdTask({
          status: 'failed',
          stage: null,
          error: { code: 'checksum_mismatch', message: 'Paczka uszkodzona (suma kontrolna).' },
          finished_at: Date.now(),
        }),
      }),
    )

    expect(screen.getByText('Błąd: Paczka uszkodzona (suma kontrolna).')).toBeInTheDocument()
    expect(screen.queryByText('Paczka uszkodzona (suma kontrolna).')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Szczegóły' }))
    expect(await screen.findAllByText('Paczka uszkodzona (suma kontrolna).')).toHaveLength(1)
  })

  it('anulowane: „Anulowano” i ✕ bez akcji pobrania (SC-E7-2-04 krok 5)', async () => {
    await renderRow(
      storedRow({ last: wdTask({ status: 'cancelled', stage: null, finished_at: Date.now() }) }),
    )

    expect(row()).toHaveAttribute('data-task-status', 'cancelled')
    expect(screen.getByText('Anulowano')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pobierz' })).not.toBeInTheDocument()
    // Anulowany wiersz zalega w pasku do TTL, gdyby ✕ nie działał dla tego stanu (SC-E7-2-04).
    expect(screen.getByRole('button', { name: 'Zamknij' })).toBeInTheDocument()
  })
})

describe('TaskRow — akcje', () => {
  it('Stop woła POST /tasks/{id}/stop (SC-E7-2-04 krok 5)', async () => {
    let stops = 0
    server.use(
      http.post(apiUrl('/api/wd/v1/tasks/task-1/stop'), () => {
        stops += 1
        return HttpResponse.json({ data: { stopped: true } })
      }),
    )
    await renderRow(storedRow({ last: wdTask() }))
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Stop' }))

    await waitFor(() => expect(stops).toBe(1))
  })

  it('✕ usuwa wiersz z magazynu (stan końcowy)', async () => {
    await renderRow(storedRow())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(onRemove).toHaveBeenCalledWith('task-1')
  })

  it('Kopiuj link zapisuje w schowku bezwzględny adres i potwierdza etykietą', async () => {
    await renderRow(storedRow())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Kopiuj link' }))

    expect(copyToClipboard).toHaveBeenCalledWith(new URL(DOWNLOAD_URL, window.location.origin).href)
    expect(await screen.findByRole('button', { name: 'Skopiowano' })).toBeInTheDocument()
  })

  it('odmowa schowka przy „Kopiuj link”: komunikat błędu zamiast ciszy (MINOR T5)', async () => {
    vi.mocked(copyToClipboard).mockResolvedValueOnce(false)
    await renderRow(storedRow())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Kopiuj link' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nie udało się skopiować — zaznacz link ręcznie',
    )
    // Pole tylko-do-odczytu z linkiem, zaznaczone do ręcznego skopiowania (SC-E67-05).
    const field = screen.getByRole('textbox', { name: 'Link do pobrania' })
    expect(field).toHaveValue(new URL(DOWNLOAD_URL, window.location.origin).href)
    expect(field).toHaveAttribute('readonly')
    expect((field as HTMLInputElement).selectionEnd).toBe((field as HTMLInputElement).value.length)
    expect(screen.queryByRole('button', { name: 'Skopiowano' })).not.toBeInTheDocument()
  })

  it('Pobierz to zwykły link z `download` — strumieniowanie przez przeglądarkę (MAJOR T5)', async () => {
    await renderRow(storedRow())

    const button = screen.getByRole('button', { name: 'Pobierz' })
    expect(button).toHaveAttribute('href', DOWNLOAD_URL)
    expect(button).toHaveAttribute('download', 'rocznik-gus.wdkb.zip')
    expect(button).not.toHaveAttribute('aria-disabled')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('link po expires_at: Pobierz nieaktywne i komunikat o wygasłym linku (MAJOR T5)', async () => {
    await renderRow(
      storedRow({
        last: wdTask({
          status: 'done',
          result: {
            download_url: DOWNLOAD_URL,
            expires_at: Date.now() - 1000,
            size_bytes: 77_594_624,
            file_name: 'rocznik-gus.wdkb.zip',
          },
        }),
      }),
    )

    // `<a>` nie wspiera atrybutu `disabled` — MUI daje `aria-disabled` (jest-dom `toBeDisabled`
    // sprawdza je tylko dla tagów formularzowych).
    expect(screen.getByRole('button', { name: 'Pobierz' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent('Link pobrania wygasł.')
  })
})
