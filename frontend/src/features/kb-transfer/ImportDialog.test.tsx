/**
 * Dialog importu — przepływ wysyłki (kontrakt WP E7-2 §5, brief T6): paczka 0 B nie startuje
 * sesji (R-ING-03), wysyłka idzie 3 porcjami z tekstem „Wysłano a/b", błąd sieci daje
 * „Wznawianie…" i wznawianie, 3 nieudane próby → „Wznów", „Anuluj" w trakcie wysyłki
 * porzuca sesję (abort + `deleteImport`), `state=invalid` → lista błędów + „Wybierz inny plik".
 */

import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  failNextUpload,
  kbDefaultSummary,
  resetKbTransfer,
  setImportPackage,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { initI18n } from '../../i18n'

import { ImportDialog } from './ImportDialog'
import type { DatasetImport } from './types'

const CREATE_ROUTE = apiUrl('/api/wd/v1/dataset-imports')
const CONTENT_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
const DELETE_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

/** Paczka 1-porcjowa (6 B — domyślny handler MSW przyjmuje dowolny rozmiar > 0). */
function smallPackage(): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00])], 'paczka.wdkb.zip', {
    type: 'application/zip',
  })
}

/** Pełny `DatasetImport` do odpowiedzi syntetycznego handlera porcji. */
function sessionBody(overrides: Partial<DatasetImport>): DatasetImport {
  return {
    import_id: 'import-test',
    file_name: 'paczka.wdkb.zip',
    size_bytes: 12_288,
    received_bytes: 0,
    chunk_size: 4_096,
    state: 'uploading',
    errors: [],
    summary: null,
    task_id: null,
    expires_at: Date.now() + 3_600_000,
    ...overrides,
  }
}

/** Atrapy wywołań dialogu: `onStarted` (start zadania) i `onClose` (zamknięcie). */
type DialogSpies = {
  onStarted: ReturnType<typeof vi.fn>
  onClose: ReturnType<typeof vi.fn>
}

async function renderDialog(): Promise<DialogSpies> {
  const onStarted = vi.fn()
  const onClose = vi.fn()
  await renderWithProviders(<ImportDialog onClose={onClose} onStarted={onStarted} />)
  return { onStarted, onClose }
}

describe('ImportDialog — przepływ wysyłki', () => {
  it('paczka 0 B: ostrzeżenie R-ING-03 bez zakładania sesji', async () => {
    const user = userEvent.setup()
    await renderDialog()
    const creates: number[] = []
    server.use(
      http.post(CREATE_ROUTE, () => {
        creates.push(1)
        return HttpResponse.json(
          { error: { code: 'validation_failed', message: 'x' } },
          { status: 400 },
        )
      }),
    )

    await user.upload(screen.getByTestId('kb-import-input'), [
      new File([], 'pusty.wdkb.zip', { type: 'application/zip' }),
    ])

    expect(await screen.findByTestId('kb-import-empty')).toBeInTheDocument()
    expect(screen.getByText('Paczka jest pusta (0 B) — wybierz inny plik.')).toBeInTheDocument()
    expect(creates, '0 B nie wywołuje POST /dataset-imports').toEqual([])
    expect(screen.getByTestId('kb-import-dropzone')).toBeInTheDocument()
  })

  it('wysyłka idzie 3 porcjami: postęp „Wysłano a/b", potem podsumowanie', async () => {
    const user = userEvent.setup()
    await renderDialog()
    const starts: number[] = []
    server.use(
      http.post(CREATE_ROUTE, async ({ request }) => {
        const body = (await request.json()) as { file_name: string; size_bytes: number }
        return HttpResponse.json(
          { data: sessionBody({ file_name: body.file_name, size_bytes: body.size_bytes }) },
          { status: 201 },
        )
      }),
      http.put(CONTENT_ROUTE, async ({ request }) => {
        const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(request.headers.get('Content-Range') ?? '')
        if (range === null) return HttpResponse.error()
        const start = Number(range[1])
        const received = Number(range[2]) + 1
        const total = Number(range[3])
        starts.push(start)
        await new Promise((resolve) => setTimeout(resolve, 120)) // okno na asercję postępu
        return HttpResponse.json({
          data: sessionBody({
            received_bytes: received,
            state: received < total ? 'uploading' : 'ready',
            summary: received < total ? null : kbDefaultSummary(),
          }),
        })
      }),
    )

    await user.upload(screen.getByTestId('kb-import-input'), [
      new File([new Uint8Array(12_288)], 'paczka.wdkb.zip', { type: 'application/zip' }),
    ])

    expect(await screen.findByText('Wysłano 4 KB/12 KB')).toBeInTheDocument()
    await screen.findByTestId('kb-import-summary')
    expect(starts, '3 porcje od 0, chunk_size i 2×chunk_size').toEqual([0, 4_096, 8_192])
  })

  it('błąd sieci porcji: „Wznawianie…" i dokończenie bez nowego wyboru pliku', async () => {
    // Fałszywy zegar: i18n inicjalizowany wcześniej (i18next wisi pod atrapą), plik wchodzi przez
    // `fireEvent` (`userEvent` pod atrapą wisi), asercje synchroniczne — `waitFor` pod atrapą wisi.
    await initI18n('pl')
    vi.useFakeTimers()
    await renderDialog()
    failNextUpload(1)
    const input = screen.getByTestId('kb-import-input')
    Object.defineProperty(input, 'files', { value: [smallPackage()], configurable: true })
    fireEvent.change(input)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByText('Wznawianie…')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    // Wznowienie: odpytanie sesji i ponowienie porcji — mikrozadania MSW po przerwie.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId('kb-import-summary')).toBeInTheDocument()
  })

  it('3 nieudane próby: stan pauzy z „Wznów", klik wznawia wysyłkę', async () => {
    await initI18n('pl')
    vi.useFakeTimers()
    await renderDialog()
    failNextUpload(4)
    const input = screen.getByTestId('kb-import-input')
    Object.defineProperty(input, 'files', { value: [smallPackage()], configurable: true })
    fireEvent.change(input)

    // Backoff 1 s / 2 s / 4 s, potem stan `paused`.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    const resume = screen.getByRole('button', { name: 'Wznów' })
    expect(resume).toBeEnabled()

    fireEvent.click(resume)
    // Wznowienie od stanu serwera: getImport + porcja — mikrozadania po wybudzeniu.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId('kb-import-summary')).toBeInTheDocument()
  })

  it('twardy błąd wysyłki po założeniu sesji: deleteImport i powrót do wyboru pliku (MINOR T6)', async () => {
    const user = userEvent.setup()
    await renderDialog()
    let deleted = false
    server.use(
      // Twardy błąd serwera po zakładającej sesji `createImport` (np. 400 `import_not_ready`).
      http.put(CONTENT_ROUTE, () =>
        HttpResponse.json({ error: { code: 'import_not_ready', message: 'x' } }, { status: 400 }),
      ),
      http.delete(DELETE_ROUTE, () => {
        deleted = true
        return HttpResponse.json({ data: { deleted: true } })
      }),
    )

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])

    expect(await screen.findByTestId('kb-import-dropzone')).toBeInTheDocument()
    expect(deleted, 'sesja po założeniu porzucona DELETE').toBe(true)
    expect(screen.getByText('Import nie jest gotowy do tego kroku.')).toBeInTheDocument()
  })

  it('„Anuluj" w trakcie wysyłki: abort + deleteImport, powrót do wyboru pliku', async () => {
    const user = userEvent.setup()
    const { onStarted } = await renderDialog()
    let deleted = false
    server.use(
      http.put(CONTENT_ROUTE, async () => {
        await new Promise((resolve) => setTimeout(resolve, 500)) // wysyłka w toku
        return HttpResponse.json({ data: sessionBody({}) })
      }),
      http.delete(DELETE_ROUTE, () => {
        deleted = true
        return HttpResponse.json({ data: { deleted: true } })
      }),
    )

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    expect(await screen.findByTestId('kb-import-upload')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(await screen.findByTestId('kb-import-dropzone')).toBeInTheDocument()
    expect(deleted, 'sesja porzucona przez DELETE').toBe(true)
    expect(onStarted).not.toHaveBeenCalled()
  })

  it('state=invalid: lista błędów z API i „Wybierz inny plik" resetuje krok 1', async () => {
    const user = userEvent.setup()
    await renderDialog()
    let deleted = false
    server.use(
      http.delete(DELETE_ROUTE, () => {
        deleted = true
        return HttpResponse.json({ data: { deleted: true } })
      }),
    )
    setImportPackage([
      { code: 'checksum_mismatch', message: 'Paczka uszkodzona (suma kontrolna).' },
    ])

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    expect(await screen.findByText('Paczka uszkodzona (suma kontrolna).')).toBeInTheDocument()
    expect(screen.queryByTestId('kb-import-summary')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Wybierz inny plik' }))
    expect(await screen.findByTestId('kb-import-dropzone')).toBeInTheDocument()
    expect(deleted, 'reset porzuca nieważną sesję').toBe(true)
  })
})
