/**
 * Zamknięcie dialogu uploadu zbioru (regresja po T1, WP E5-H6a): „Gotowe”/„Anuluj” działa w fazie
 * parsowania — wysyłka już się skończyła, ale trwa jeszcze `documents/parse` — a blokuje się
 * TYLKO w trakcie realnego transferu plików. Osobny plik, bo `UploadDialog.test.tsx` ma na HEAD
 * 294 linie, a limit `max-lines` wynosi 300 (`eslint.config.js`, DEC-098); istniejący plik bez zmian.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, documentsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { UploadDialog } from './UploadDialog'

afterEach(cleanup)

beforeEach(() => {
  uploadFormMock.mockReset()
})

function file(name: string): File {
  return new File([name], name, { type: 'application/pdf' })
}

/** Plik 0 B — tak wygląda `File` od przeglądarki bez dostępu do katalogu (Chrome/Flatpak). */
function emptyFile(name: string): File {
  return new File([], name, { type: 'application/pdf' })
}

/** Atrapa uploadu: każde żądanie przyjmuje kolejny dokument (`doc-1`, `doc-2`, …). */
function acceptUploads(): void {
  let sequence = 0
  uploadFormMock.mockImplementation(async () => {
    sequence += 1
    return [{ id: `doc-${sequence}` }]
  })
}

const PARSE_URL = apiUrl('/api/v1/datasets/:datasetId/documents/parse')

/**
 * Trasy `documents` z MSW; `holdParse` zostawia żądanie parsowania WSTRZYMANE (obietnica
 * nierozwiązana) — symuluje zakończoną wysyłkę, po której trwa jeszcze wywołanie parsowania.
 */
function useDocuments(options: { holdParse?: boolean } = {}): void {
  if (options.holdParse === true) {
    server.use(
      http.post(PARSE_URL, () => new Promise<Response>(() => undefined)),
      ...documentsHandlers([]),
    )
    return
  }
  server.use(...documentsHandlers([]))
}

/**
 * Rodzic z własnym stanem `open` — po „Gotowe” dialog zostaje ZAMONTOWANY (tylko ukryty), więc
 * test widzi, co robi z kolejką plików jego lokalny stan. Przycisk poza dialogiem otwiera go
 * ponownie (kontrakt WP E5-H6a §C1: zamknięcie czyści kolejkę).
 */
function UploadDialogHarness(props: {
  onUploaded?: () => void
  onClose?: () => void
}): JSX.Element {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button
        data-testid="reopen-dialog"
        onClick={() => {
          setOpen(true)
        }}
      >
        otwórz dialog
      </button>
      <UploadDialog
        open={open}
        datasetId="ds-1"
        onClose={() => {
          setOpen(false)
          props.onClose?.()
        }}
        onUploaded={props.onUploaded}
      />
    </>
  )
}

function closeButton(): HTMLElement {
  // Po zakończeniu przesyłania przycisk nosi „Gotowe” (SC-E5-H9-03); wcześniej „Anuluj”.
  return screen.getByRole('button', { name: /Gotowe|Anuluj/ })
}

describe('UploadDialog — zamykanie', () => {
  // Regresja po T1: wysyłka zakończona (wiersz „Przesłano”), a parsowanie wisi nierozwiązane.
  it('zamyka dialog w fazie parsowania i czyści kolejkę', async () => {
    acceptUploads()
    useDocuments({ holdParse: true })
    const onClose = vi.fn()
    await renderWithProviders(<UploadDialogHarness onClose={onClose} />)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('sample.pdf')])
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(screen.getByText('Przesłano')).toBeInTheDocument())

    // Koniec przesyłania (SC-E5-H9-03): stopka „Przesłano 1 z 1”, przycisk „Gotowe” z fokusem.
    expect(screen.getByTestId('upload-summary')).toHaveTextContent('Przesłano 1 z 1')
    const done = screen.getByRole('button', { name: 'Gotowe' })
    expect(done).toBeInTheDocument()
    expect(done).toHaveFocus()

    await user.click(done)
    expect(onClose).toHaveBeenCalledTimes(1)

    // Przycisk rodzica jest poza modalem (`aria-hidden` przy otwartym dialogu) — klikamy testidem.
    fireEvent.click(screen.getByTestId('reopen-dialog'))
    expect(await screen.findByTestId('upload-dropzone')).toBeInTheDocument()
    expect(screen.queryByText('sample.pdf')).not.toBeInTheDocument()
  })

  // Kontrakt WP E5-H6a §C1 p. 2: w trakcie realnego transferu okno nie zamyka się w połowie.
  it('w trakcie transferu plików „Anuluj” nic nie robi (okno zostaje otwarte)', async () => {
    let release: () => void = () => undefined
    uploadFormMock.mockImplementation(
      () =>
        new Promise<unknown>((resolve) => {
          release = () => {
            resolve([{ id: 'doc-1' }])
          }
        }),
    )
    useDocuments()
    const onClose = vi.fn()
    await renderWithProviders(<UploadDialogHarness onClose={onClose} />)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('g.txt')])
    await user.click(screen.getByTestId('upload-start'))
    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))

    await user.click(closeButton())
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('g.txt')).toBeInTheDocument()

    release()
    await waitFor(() => expect(screen.getByText('Przesłano')).toBeInTheDocument())
  })

  // SC-E5-H9-03 krok 3: odrzucony plik (tu: 0 B) zostaje w mianowniku podsumowania.
  it('podsumowanie liczy odrzucony plik 0 B: „Przesłano 2 z 3”', async () => {
    acceptUploads()
    useDocuments()
    await renderWithProviders(<UploadDialogHarness />)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [
      file('a.pdf'),
      file('b.pdf'),
      emptyFile('pusty.pdf'),
    ])
    expect(screen.getByTestId('upload-unreadable')).toBeInTheDocument()
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(screen.getByTestId('upload-summary')).toBeInTheDocument())
    expect(screen.getByTestId('upload-summary')).toHaveTextContent('Przesłano 2 z 3')
  })
})
