/**
 * Testy `UploadDialog` (kontrakt WP E3-3b §T3): wybór plików z inputa i dropu (z pomijaniem
 * duplikatów), pasek postępu z XHR-a, „Parsuj po przesłaniu” włączony/wyłączony oraz błąd
 * jednego z trzech plików. `uploadForm` (XHR) podmieniamy atrapą, bo w jsdom nie ma wysyłania;
 * parsowanie idzie prawdziwą trasą przez MSW (`documentsHandlers().onRequest`).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { unwrapEnvelope } from '../../../api/envelope'
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

/** Atrapa uploadu: każde żądanie przyjmuje kolejny dokument (`doc-1`, `doc-2`, …). */
function acceptUploads(): void {
  let sequence = 0
  uploadFormMock.mockImplementation(async () => {
    sequence += 1
    return [{ id: `doc-${sequence}` }]
  })
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve: () => void = () => undefined
  const promise = new Promise<void>((resolution) => {
    resolve = resolution
  })
  return { promise, resolve }
}

/** Rejestruje MSW z zapisem ciał żądań `parse`; `failParse` zwraca błąd domenowy z tej trasy. */
function useDocuments(options: { failParse?: boolean } = {}): {
  parseCalls: { document_ids: string[] }[]
} {
  const parseCalls: { document_ids: string[] }[] = []
  const handlers = documentsHandlers([], {
    onRequest: (kind, body) => {
      if (kind === 'parse') parseCalls.push(body as { document_ids: string[] })
    },
  })
  if (options.failParse === true) {
    server.use(
      http.post(apiUrl('/api/v1/datasets/:datasetId/documents/parse'), () =>
        HttpResponse.json({ code: 1, message: 'błąd parsowania', data: null }),
      ),
      ...handlers,
    )
  } else {
    server.use(...handlers)
  }
  return { parseCalls }
}

function renderDialog(onUploaded?: () => void) {
  return renderWithProviders(
    <UploadDialog open datasetId="ds-1" onClose={() => undefined} onUploaded={onUploaded} />,
  )
}

/**
 * Rodzic z własnym stanem `open` — po „Gotowe” dialog zostaje ZAMONTOWANY (tylko ukryty),
 * więc test widzi, co robi z kolejką plików jego lokalny stan. Przycisk poza dialogiem
 * otwiera go ponownie (kontrakt WP E5-H6a §C1: zamknięcie czyści kolejkę).
 */
function UploadDialogHarness(props: { onUploaded?: () => void }): JSX.Element {
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
        }}
        onUploaded={props.onUploaded}
      />
    </>
  )
}

function parseToggle(): HTMLElement {
  return within(screen.getByTestId('upload-parse-toggle')).getByRole('switch')
}

describe('UploadDialog', () => {
  it('przesyła 3 pliki wybrane inputem i parsuje je po przesłaniu', async () => {
    acceptUploads()
    const { parseCalls } = useDocuments()
    const onUploaded = vi.fn()
    await renderDialog(onUploaded)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [
      file('a.pdf'),
      file('b.pdf'),
      file('c.pdf'),
    ])

    expect(screen.getByTestId('upload-progress-0')).toBeInTheDocument()
    expect(parseToggle()).toBeChecked()

    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
    expect(uploadFormMock).toHaveBeenCalledTimes(3)
    expect(parseCalls).toEqual([{ document_ids: ['doc-1', 'doc-2', 'doc-3'] }])
    // T15b (SC-E5-H9-03 k. 2): po pełnym sukcesie „Prześlij” wyłączone — nie ma czego ponawiać.
    expect(screen.getByTestId('upload-start')).toBeDisabled()
  })

  it('przyjmuje pliki z dropu, pomija duplikaty i pokazuje postęp, blokując wybór w trakcie', async () => {
    const gate = deferred()
    uploadFormMock.mockImplementation(async (_path: string, _form: FormData, options) => {
      options?.onProgress?.(50, 100)
      await gate.promise
      return [{ id: 'doc-1' }]
    })
    const { parseCalls } = useDocuments()
    await renderDialog()
    const user = userEvent.setup()

    const dropzone = screen.getByTestId('upload-dropzone')
    expect(dropzone).toHaveAttribute('tabindex', '0')
    fireEvent.drop(dropzone, { dataTransfer: { files: [file('a.pdf')] } })
    fireEvent.drop(dropzone, { dataTransfer: { files: [file('a.pdf')] } })

    expect(screen.getAllByText('a.pdf')).toHaveLength(1)
    expect(screen.queryByTestId('upload-progress-1')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() =>
      expect(screen.getByTestId('upload-progress-0')).toHaveAttribute('aria-valuenow', '50'),
    )
    expect(screen.getByTestId('upload-input')).toBeDisabled()
    expect(screen.getByTestId('upload-start')).toBeDisabled()
    fireEvent.drop(dropzone, { dataTransfer: { files: [file('b.pdf')] } })
    expect(screen.queryByText('b.pdf')).not.toBeInTheDocument()

    gate.resolve()
    // T15b: koniec uploadu z pełnym sukcesem wyłącza „Prześlij” (było: ponownie włączony).
    await waitFor(() => expect(screen.getByTestId('upload-start')).toBeDisabled())
    expect(parseCalls).toHaveLength(1)
  })

  it('strefa drop i przycisk „Wybierz pliki” otwierają wybór plików, także z klawiatury', async () => {
    acceptUploads()
    useDocuments()
    await renderDialog()
    const user = userEvent.setup()
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)

    const dropzone = screen.getByTestId('upload-dropzone')
    await user.click(dropzone)
    await user.click(screen.getByRole('button', { name: 'Wybierz pliki' }))
    fireEvent.keyDown(dropzone, { key: 'Enter' })
    fireEvent.keyDown(dropzone, { key: ' ' })
    expect(click).toHaveBeenCalledTimes(4)

    fireEvent.keyDown(dropzone, { key: 'a' })
    expect(click).toHaveBeenCalledTimes(4)
    click.mockRestore()
  })

  it('wyłączony przełącznik nie wysyła żądania parsowania', async () => {
    acceptUploads()
    const { parseCalls } = useDocuments()
    const onUploaded = vi.fn()
    await renderDialog(onUploaded)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('a.pdf')])
    await user.click(parseToggle())
    expect(parseToggle()).not.toBeChecked()

    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
    expect(uploadFormMock).toHaveBeenCalledTimes(1)
    expect(parseCalls).toHaveLength(0)
  })

  it('błąd jednego z trzech plików nie przerywa pozostałych, a parse dostaje 2 ID', async () => {
    let call = 0
    uploadFormMock.mockImplementation(async () => {
      call += 1
      if (call === 2) throw new Error('plik za duży')
      return [{ id: `doc-${call}` }]
    })
    const { parseCalls } = useDocuments()
    const onUploaded = vi.fn()
    await renderDialog(onUploaded)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [
      file('a.pdf'),
      file('b.pdf'),
      file('c.pdf'),
    ])
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
    expect(screen.getAllByText('Przesłano')).toHaveLength(2)
    expect(screen.getAllByText('Błąd przesyłania')).toHaveLength(1)
    expect(uploadFormMock).toHaveBeenCalledTimes(3)
    expect(parseCalls).toEqual([{ document_ids: ['doc-1', 'doc-3'] }])
    // T15b: element z błędem w kolejce — „Prześlij” zostaje aktywne (ponowienie).
    expect(screen.getByTestId('upload-start')).not.toBeDisabled()
  })

  it('błąd parsowania pokazuje Alert z komunikatem ogólnym', async () => {
    acceptUploads()
    useDocuments({ failParse: true })
    const onUploaded = vi.fn()
    await renderDialog(onUploaded)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('a.pdf')])
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Operacja nie powiodła się.'),
    )
    expect(onUploaded).toHaveBeenCalledTimes(1)
  })

  // Kontrakt WP E5-H6a §C1 (usterka U4): zamknięcie dialogu czyści kolejkę plików.
  it('zamknięcie dialogu czyści kolejkę plików', async () => {
    acceptUploads()
    useDocuments()
    const onUploaded = vi.fn()
    await renderWithProviders(<UploadDialogHarness onUploaded={onUploaded} />)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('a.pdf')])
    await user.click(screen.getByTestId('upload-start'))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Gotowe' }))
    // Przycisk rodzica jest poza modalem (`aria-hidden` przy otwartym dialogu) — klikamy testidem.
    fireEvent.click(screen.getByTestId('reopen-dialog'))

    expect(await screen.findByTestId('upload-dropzone')).toBeInTheDocument()
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
  })

  // Kontrakt WP E5-H6a §C1 (usterka p. 2): odrzucony plik pokazuje `ApiError.message` z koperty.
  // jsdomowy `FormData` z blobem nie przechodzi przez przechwytywacz MSW (błąd `_buffer`,
  // `docs/modules/frontend-files.md`), dlatego odpowiedź koperty rozpakowujemy PRAWDZIWYM
  // `unwrapEnvelope` — tą samą drogą, którą `uploadForm` zamienia `code ≠ 0` na `ApiError`.
  it('wiersz odrzuconego pliku pokazuje przyczynę z koperty API', async () => {
    const reason = 'This type of file has not been supported yet!'
    uploadFormMock.mockImplementation(() =>
      Promise.resolve().then(() =>
        unwrapEnvelope<never>({ code: 101, message: reason, data: null }, 200),
      ),
    )
    const onUploaded = vi.fn()
    await renderDialog(onUploaded)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [file('x.odp')])
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('alert')).toHaveTextContent(reason)
    expect(screen.getByText('Błąd przesyłania')).toBeInTheDocument()
  })
})
