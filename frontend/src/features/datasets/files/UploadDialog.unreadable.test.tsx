/**
 * Ostrzeżenie o plikach nieczytelnych w `UploadDialog` (kontrakt WP E5-H8d §C3, SC-E5-H8d-01):
 * plik 0 B (przeglądarka bez dostępu do katalogu, np. Chrome z Flatpaka) nie wchodzi do kolejki —
 * pod strefą zostaje Alert `upload-unreadable` z jego nazwą; mieszanka z dropu trafia do kolejki
 * bez pustych plików, a udany wybór czytelnych plików gasi ostrzeżenie. Osobny plik, bo
 * `UploadDialog.test.tsx` stoi na granicy limitu `max-lines` 300 (eslint.config.js, DEC-098).
 */

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { UploadDialog } from './UploadDialog'

afterEach(cleanup)

function file(name: string): File {
  return new File([name], name, { type: 'application/pdf' })
}

/** Plik 0 B — tak wygląda `File` od przeglądarki bez dostępu do katalogu (Chrome/Flatpak). */
function emptyFile(name: string): File {
  return new File([], name, { type: 'application/pdf' })
}

async function renderDialog() {
  return renderWithProviders(<UploadDialog open datasetId="ds-1" onClose={() => undefined} />)
}

describe('UploadDialog — pliki nieczytelne (0 B)', () => {
  it('drop pliku 0 B: brak w kolejce i Alert z nazwą pliku', async () => {
    await renderDialog()

    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf')] },
    })

    const warning = screen.getByTestId('upload-unreadable')
    expect(warning).toHaveTextContent('Nie można odczytać pliku »raport.pdf« (0 B).')
    expect(screen.getByTestId('upload-start')).toBeDisabled()
  })

  it('mieszanka z dropu: tylko czytelny plik w kolejce, Alert wymienia pusty', async () => {
    await renderDialog()

    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf'), file('sample.pdf')] },
    })

    expect(screen.getByTestId('upload-unreadable')).toHaveTextContent('raport.pdf')
    expect(screen.getByText('sample.pdf')).toBeInTheDocument()
    expect(screen.getByTestId('upload-start')).toBeEnabled()
  })

  it('wybór pliku 0 B: tekst „Plik jest pusty (0 B)” bez słowa „Flatpak”', async () => {
    await renderDialog()
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [emptyFile('pusty.pdf')])

    const warning = screen.getByTestId('upload-unreadable')
    expect(warning).toHaveTextContent('Plik jest pusty (0 B): »pusty.pdf«.')
    expect(warning.textContent).not.toContain('Flatpak')
    expect(screen.getByTestId('upload-start')).toBeDisabled()
  })

  // Kontrakt §C3: wybór bez plików nieczytelnych CZYŚCI ostrzeżenie (SC-01 krok 3).
  it('udany wybór czytelnego pliku gasi ostrzeżenie po dropie 0 B', async () => {
    await renderDialog()
    const user = userEvent.setup()

    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [emptyFile('raport.pdf')] },
    })
    expect(screen.getByTestId('upload-unreadable')).toBeInTheDocument()

    await user.upload(screen.getByTestId('upload-input'), [file('sample.pdf')])

    expect(screen.queryByTestId('upload-unreadable')).not.toBeInTheDocument()
    expect(screen.getByText('sample.pdf')).toBeInTheDocument()
  })

  // SC-E5-H9-03 krok 3: odrzucone 0 B zostają w mianowniku podsumowania także wtedy, gdy
  // ostrzeżenie („ostatni drop”) już zgasło po dobrym wyborze.
  it('podsumowanie liczy odrzucony 0 B z wcześniejszego dropu: „Przesłano 1 z 2”', async () => {
    uploadFormMock.mockResolvedValue([{ id: 'doc-1' }])
    await renderDialog()
    const user = userEvent.setup()

    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [emptyFile('pusty.pdf')] },
    })
    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [file('sample.pdf')] },
    })
    expect(screen.queryByTestId('upload-unreadable')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('upload-start'))
    await waitFor(() =>
      expect(screen.getByTestId('upload-summary')).toHaveTextContent('Przesłano 1 z 2'),
    )
  })
})
