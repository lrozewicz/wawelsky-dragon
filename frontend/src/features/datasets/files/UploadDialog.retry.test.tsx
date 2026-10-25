/**
 * Ponowienie uploadu (SC-E67-04, WP E67-z1a): po odrzuceniu jednego pliku kolejny klik „Prześlij”
 * wysyła WYŁĄCZNIE ten plik (bez duplikatów już przesłanych), a po pełnym sukcesie „Prześlij”
 * jest nieaktywne. Transport (`uploadForm`) podmieniony atrapą — liczymy żądania per plik.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { documentsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

const { uploadFormMock } = vi.hoisted(() => ({ uploadFormMock: vi.fn() }))

vi.mock('../../../api/upload', () => ({ uploadForm: uploadFormMock }))

import { UploadDialog } from './UploadDialog'

afterEach(cleanup)

beforeEach(() => {
  uploadFormMock.mockReset()
  server.use(...documentsHandlers([]))
})

function file(name: string): File {
  return new File([name], name, { type: 'application/pdf' })
}

/** Nazwy plików wysłanych w kolejnych żądaniach (`FormData` pola `file`). */
function sentNames(): string[] {
  return uploadFormMock.mock.calls
    .map(([, form]) => (form as FormData).get('file') as File)
    .map((f) => f.name)
}

/** Atrapa: `b.pdf` jest odrzucany, dopóki `rejectB.value` jest prawdą. */
function mockUploads(rejectB: { value: boolean }): void {
  let sequence = 0
  uploadFormMock.mockImplementation(async (_url: string, form: FormData) => {
    const name = (form.get('file') as File).name
    if (name === 'b.pdf' && rejectB.value) throw new Error('Plik za duży')
    sequence += 1
    return [{ id: `doc-${sequence}` }]
  })
}

describe('UploadDialog — ponowienie nieudanych', () => {
  it('drugi klik „Prześlij” wysyła tylko plik z błędem, a po sukcesie przycisk jest nieaktywny', async () => {
    const rejectB = { value: true }
    mockUploads(rejectB)
    await renderWithProviders(<UploadDialog open datasetId="ds-1" onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.upload(screen.getByTestId('upload-input'), [
      file('a.pdf'),
      file('b.pdf'),
      file('c.pdf'),
    ])
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() =>
      expect(screen.getByTestId('upload-summary')).toHaveTextContent('Przesłano 2 z 3'),
    )
    expect(screen.getAllByText('Przesłano', { exact: true })).toHaveLength(2)
    expect(screen.getByRole('alert')).toHaveTextContent('Plik za duży')
    expect(sentNames()).toEqual(['a.pdf', 'b.pdf', 'c.pdf'])
    expect(screen.getByTestId('upload-start')).toBeEnabled()
    // SC-V12-08 k2: etykieta mówi, co pójdzie ponownie, a podpowiedź — czego NIE wyśle drugi raz.
    expect(screen.getByTestId('upload-start')).toHaveTextContent('Prześlij ponownie nieudane (1)')
    expect(screen.getByTestId('upload-start')).toHaveAttribute(
      'aria-describedby',
      'upload-retry-hint',
    )
    expect(
      screen.getByText(
        'Ponownie zostaną przesłane tylko nieudane pliki — udane nie zostaną wysłane drugi raz.',
      ),
    ).toHaveAttribute('id', 'upload-retry-hint')

    uploadFormMock.mockClear()
    rejectB.value = false
    await user.click(screen.getByTestId('upload-start'))

    await waitFor(() =>
      expect(screen.getByTestId('upload-summary')).toHaveTextContent('Przesłano 3 z 3'),
    )
    // Dokładnie jedno nowe żądanie i tylko dla błędnego pliku — a/c nie są wysyłane drugi raz.
    expect(sentNames()).toEqual(['b.pdf'])
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getAllByText('Przesłano', { exact: true })).toHaveLength(3)
    // Pasek pozycji „Przesłano” stoi na 100 % (też po ponowieniu, gdy transport nie zgłosił postępu).
    for (const index of [0, 1, 2]) {
      expect(screen.getByTestId(`upload-progress-${String(index)}`)).toHaveAttribute(
        'aria-valuenow',
        '100',
      )
    }

    expect(screen.getByTestId('upload-start')).toBeDisabled()
    expect(screen.getByTestId('upload-close')).toHaveTextContent('Gotowe')
  })
})
