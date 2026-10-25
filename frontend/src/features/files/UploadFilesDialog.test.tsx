/**
 * Testy `UploadFilesDialog` (kontrakt WP E4-5c §7, przykład 9): wybór plików i drop startują
 * `uploadFiles`, pozycje pokazują `done`/`error`, po zakończeniu pętli unieważniane jest
 * `fileKeys.all`, a okno zamyka tylko przycisk. `uploadForm` (XHR) podmieniamy atrapą — w jsdom
 * ciało `multipart/form-data` nie przechodzi przez przechwytywacz MSW (błąd `_buffer`).
 */

import { useState } from 'react'
import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/envelope'
import { filesFixtureRoot } from '../../test/msw/handlers'
import { renderWithProviders } from '../../test/renderWithProviders'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { DEFAULT_FILES_QUERY, fileKeys } from './queries'
import { UploadFilesDialog } from './UploadFilesDialog'

afterEach(cleanup)

beforeEach(() => {
  uploadFormMock.mockReset()
})

function file(name: string): File {
  return new File(['x'], name, { type: 'text/plain' })
}

function makeClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  client.setQueryData(fileKeys.list(DEFAULT_FILES_QUERY), {
    files: [],
    total: 0,
    parentFolder: filesFixtureRoot,
  })
  return client
}

async function renderDialog(onClose: () => void = () => undefined) {
  const client = makeClient()
  const result = await renderWithProviders(
    <UploadFilesDialog open parentId="root-1" onClose={onClose} />,
    { queryClient: client },
  )
  return { ...result, client }
}

function item(index: number): HTMLElement {
  return screen.getByTestId(`files-upload-item-${String(index)}`)
}

/** Plik 0 B — tak wygląda `File` od przeglądarki bez dostępu do katalogu (Chrome/Flatpak). */
function emptyFile(name: string): File {
  return new File([], name, { type: 'text/plain' })
}

describe('UploadFilesDialog', () => {
  it('przesyła 2 pliki: pierwszy `done`, drugi `error`, i unieważnia `fileKeys.all`', async () => {
    let call = 0
    uploadFormMock.mockImplementation(async () => {
      call += 1
      if (call === 2) throw new Error('Internal Server Error')
      return {}
    })
    const onClose = vi.fn()
    const { client } = await renderDialog(onClose)
    const user = userEvent.setup()

    expect(screen.getByTestId('files-upload-input')).toBeInTheDocument()
    await user.upload(screen.getByTestId('files-upload-input'), [file('a.txt'), file('b.pdf')])

    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(2))
    // Stan drugiej pozycji zamyka pętlę `uploadFiles`, więc oba wyniki są już zastosowane.
    await waitFor(() => expect(within(item(1)).getByText('Błąd przesyłania')).toBeInTheDocument())
    expect(within(item(0)).getByText('Przesłano')).toBeInTheDocument()
    expect(within(item(1)).getByText('Internal Server Error')).toBeInTheDocument()

    await waitFor(() =>
      expect(client.getQueryState(fileKeys.list(DEFAULT_FILES_QUERY))?.isInvalidated).toBe(true),
    )

    // Koniec przesyłania (SC-E5-H9-03): podsumowanie z odrzuconym plikiem w mianowniku,
    // główne „Gotowe” z fokusem zamyka dialog.
    expect(screen.getByTestId('files-upload-summary')).toHaveTextContent('Przesłano 1 z 2')
    const done = screen.getByRole('button', { name: 'Gotowe' })
    expect(done).toHaveFocus()
    await user.click(done)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('przyjmuje pliki z dropu i również startuje wysyłanie', async () => {
    uploadFormMock.mockResolvedValue({})
    await renderDialog()

    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [file('c.txt')] },
    })

    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(within(item(0)).getByText('Przesłano')).toBeInTheDocument())
  })

  // SC-E5-H9-03 krok 3: odrzucony plik 0 B (nigdy nie wchodzi do `items`) zostaje w mianowniku.
  it('podsumowanie liczy odrzucony plik 0 B z dropu: „Przesłano 1 z 2”', async () => {
    uploadFormMock.mockResolvedValue({})
    await renderDialog()

    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [emptyFile('pusty.txt'), file('a.txt')] },
    })
    expect(screen.getByTestId('upload-unreadable')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByTestId('files-upload-summary')).toHaveTextContent('Przesłano 1 z 2'),
    )
  })

  it('pokazuje postęp z XHR-a na pasku pozycji', async () => {
    let release: () => void = () => undefined
    uploadFormMock.mockImplementation(async (_path: string, _form: FormData, options) => {
      options?.onProgress?.(50, 100)
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return {}
    })
    await renderDialog()
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('d.txt')])

    await waitFor(() =>
      expect(within(item(0)).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50'),
    )
    release()
  })

  it('przycisk „Anuluj” woła `onClose` (okno nie zamyka się samo)', async () => {
    uploadFormMock.mockResolvedValue({})
    const onClose = vi.fn()
    await renderDialog(onClose)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('files-upload-close'))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('pusty wybór i upuszczenie w trakcie wysyłania nic nie robią', async () => {
    let release: () => void = () => undefined
    uploadFormMock.mockImplementation(
      () =>
        new Promise<unknown>((resolve) => {
          release = () => resolve({})
        }),
    )
    await renderDialog()
    const user = userEvent.setup()

    // Zmiana bez plików: `start([])` wychodzi od razu.
    fireEvent.change(screen.getByTestId('files-upload-input'))
    expect(uploadFormMock).not.toHaveBeenCalled()

    await user.upload(screen.getByTestId('files-upload-input'), [file('e.txt')])
    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))

    // Upuszczenie w trakcie wysyłania jest ignorowane.
    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [file('f.txt')] },
    })
    expect(uploadFormMock).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('f.txt')).not.toBeInTheDocument()
    release()
  })

  it('po zamknięciu i ponownym otwarciu dialogu lista plików jest pusta', async () => {
    uploadFormMock.mockResolvedValue({})
    // Dialog sterowany z zewnątrz (jak rodzic w aplikacji): przycisk zamykania tylko zmienia `open`,
    // więc komponent pozostaje zamontowany i sam musi wyczyścić kolejkę (kontrakt C1).
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <>
          <button data-testid="reopen" onClick={() => setOpen(true)}>
            Otwórz
          </button>
          <UploadFilesDialog open={open} parentId="root-1" onClose={() => setOpen(false)} />
        </>
      )
    }
    await renderWithProviders(<Harness />, { queryClient: makeClient() })
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('a.txt')])
    await waitFor(() => expect(within(item(0)).getByText('Przesłano')).toBeInTheDocument())

    await user.click(screen.getByTestId('files-upload-close'))
    await waitFor(() => expect(screen.queryByTestId('files-upload-input')).not.toBeInTheDocument())

    await user.click(screen.getByTestId('reopen'))
    await waitFor(() => expect(screen.getByTestId('files-upload-input')).toBeInTheDocument())
    expect(screen.queryByTestId('files-upload-item-0')).not.toBeInTheDocument()
  })

  it('pokazuje komunikat z koperty API pod nazwą pliku w elemencie role="alert"', async () => {
    const message = 'This type of file has not been supported yet!'
    uploadFormMock.mockRejectedValue(new ApiError(102, message, 200))
    await renderDialog()
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('x.unsupported')])

    const alert = await within(item(0)).findByRole('alert')
    expect(alert).toHaveTextContent(message)
  })

  // SC-V13-13 (T5b): komunikat serwera w pozycji uploadu tłumaczony jak w bazie — kod 500
  // z sufiksem (w. 1) i 102 z tekstem file_suffix (w. 2, trasa linku) → jeden szablon.
  it('błąd 500 z sufiksem serwera tłumaczy na PL', async () => {
    uploadFormMock.mockRejectedValue(
      new ApiError(500, 'setup.exe: This type of file has not been supported yet!', 200),
    )
    await renderDialog()
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('setup.exe')])

    const alert = await within(item(0)).findByRole('alert')
    expect(alert).toHaveTextContent('Nieobsługiwany typ pliku: setup.exe')
    expect(alert).not.toHaveTextContent('has not been supported yet')
  })

  it('błąd 102 z tekstem file_suffix tłumaczy na EN', async () => {
    uploadFormMock.mockRejectedValue(new ApiError(102, 'file type not supported: setup.exe', 200))
    const client = makeClient()
    await renderWithProviders(
      <UploadFilesDialog open parentId="root-1" onClose={() => undefined} />,
      {
        queryClient: client,
        language: 'en',
      },
    )
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('setup.exe')])

    const alert = await within(item(0)).findByRole('alert')
    expect(alert).toHaveTextContent('Unsupported file type: setup.exe')
    expect(alert).not.toHaveTextContent('file type not supported')
  })

  it('w trakcie wysyłania „Anuluj” nic nie robi (okno zostaje otwarte)', async () => {
    let release: () => void = () => undefined
    uploadFormMock.mockImplementation(
      () =>
        new Promise<unknown>((resolve) => {
          release = () => resolve({})
        }),
    )
    const onClose = vi.fn()
    await renderDialog(onClose)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [file('g.txt')])
    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))

    await user.click(screen.getByTestId('files-upload-close'))
    expect(onClose).not.toHaveBeenCalled()
    expect(within(item(0)).getByText('g.txt')).toBeInTheDocument()

    release()
  })

  it('strefa upuszczania otwiera wybór plików także z klawiatury', async () => {
    uploadFormMock.mockResolvedValue({})
    await renderDialog()
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)

    const dropzone = screen.getByTestId('files-upload-dropzone')
    fireEvent.keyDown(dropzone, { key: 'Enter' })
    fireEvent.keyDown(dropzone, { key: ' ' })
    expect(click).toHaveBeenCalledTimes(2)

    fireEvent.keyDown(dropzone, { key: 'a' })
    expect(click).toHaveBeenCalledTimes(2)
    click.mockRestore()
  })
})
