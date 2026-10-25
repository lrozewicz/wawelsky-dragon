/**
 * Ostrzeżenie o plikach nieczytelnych w `UploadFilesDialog` (kontrakt WP E5-H8d §C3, SC-E5-H8d-01):
 * plik 0 B (przeglądarka bez dostępu do katalogu) nie startuje wysyłki — pod strefą zostaje Alert
 * `upload-unreadable` z jego nazwą; mieszanka z dropu wysyła wyłącznie czytelne pliki, a udany
 * wybór gasi ostrzeżenie. Osobny plik, bo `UploadFilesDialog.test.tsx` zbliża się do limitu
 * `max-lines` 300 (eslint.config.js, DEC-098).
 */

import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { UploadFilesDialog } from './UploadFilesDialog'

afterEach(cleanup)

function file(name: string): File {
  return new File(['x'], name, { type: 'text/plain' })
}

/** Plik 0 B — tak wygląda `File` od przeglądarki bez dostępu do katalogu (Chrome/Flatpak). */
function emptyFile(name: string): File {
  return new File([], name, { type: 'application/pdf' })
}

async function renderDialog() {
  return renderWithProviders(<UploadFilesDialog open parentId="root-1" onClose={() => undefined} />)
}

describe('UploadFilesDialog — pliki nieczytelne (0 B)', () => {
  it('drop pliku 0 B: wysyłka nie startuje, Alert z nazwą pliku', async () => {
    await renderDialog()

    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf')] },
    })

    const warning = screen.getByTestId('upload-unreadable')
    expect(warning).toHaveTextContent('Nie można odczytać pliku »raport.pdf« (0 B).')
    expect(uploadFormMock).not.toHaveBeenCalled()
    expect(screen.queryByTestId('files-upload-item-0')).not.toBeInTheDocument()
  })

  it('mieszanka z dropu: wysyła wyłącznie czytelny plik, Alert wymienia pusty', async () => {
    uploadFormMock.mockResolvedValue({})
    await renderDialog()

    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf'), file('sample.pdf')] },
    })

    expect(screen.getByTestId('upload-unreadable')).toHaveTextContent('raport.pdf')
    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))
    expect(
      within(screen.getByTestId('files-upload-item-0')).getByText('sample.pdf'),
    ).toBeInTheDocument()
  })

  it('wybór pliku 0 B: tekst „Plik jest pusty (0 B)” bez słowa „Flatpak”, bez wysyłki', async () => {
    await renderDialog()
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('files-upload-input'), [emptyFile('pusty.pdf')])

    const warning = screen.getByTestId('upload-unreadable')
    expect(warning).toHaveTextContent('Plik jest pusty (0 B): »pusty.pdf«.')
    expect(warning.textContent).not.toContain('Flatpak')
    expect(uploadFormMock).not.toHaveBeenCalled()
  })

  // Kontrakt §C3: wybór bez plików nieczytelnych CZYŚCI ostrzeżenie (SC-01 krok 3).
  it('udany wybór czytelnego pliku gasi ostrzeżenie i startuje wysyłkę', async () => {
    uploadFormMock.mockResolvedValue({})
    await renderDialog()
    const user = userEvent.setup()

    fireEvent.drop(screen.getByTestId('files-upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf')] },
    })
    expect(screen.getByTestId('upload-unreadable')).toBeInTheDocument()

    await user.upload(screen.getByTestId('files-upload-input'), [file('sample.pdf')])

    expect(screen.queryByTestId('upload-unreadable')).not.toBeInTheDocument()
    await waitFor(() => expect(uploadFormMock).toHaveBeenCalledTimes(1))
  })
})
