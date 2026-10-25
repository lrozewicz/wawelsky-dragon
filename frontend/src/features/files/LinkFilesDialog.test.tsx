/**
 * Testy `LinkFilesDialog` (kontrakt WP E4-5c §7, przykład 7–8): wielokrotny wybór datasetów,
 * `mode=add` tylko z przełącznikiem „Dopisuj”, brak wyboru blokuje przycisk, brak datasetów
 * pokazuje komunikat, a błąd koperty ląduje w `Alert`.
 */

import { useState } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  filesFixtureItems,
  fixtureDatasetDetail,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { LinkFilesDialog } from './LinkFilesDialog'

afterEach(cleanup)

const FILE = filesFixtureItems.find((item) => item.id === 'file-1')!

function seedDatasets(): void {
  server.use(
    ...datasetHandlers([
      fixtureDatasetDetail({ id: 'ds-1', name: 'Baza wiedzy' }),
      fixtureDatasetDetail({ id: 'ds-2', name: 'Inna baza' }),
    ]),
  )
}

function captureLink(): { urls: string[]; bodies: unknown[] } {
  const urls: string[] = []
  const bodies: unknown[] = []
  server.use(
    http.post(apiUrl('/api/v1/files/link-to-datasets'), async ({ request }) => {
      urls.push(request.url)
      bodies.push(await request.json())
      return HttpResponse.json({ code: 0, message: '', data: true })
    }),
  )
  return { urls, bodies }
}

describe('LinkFilesDialog', () => {
  it('łączy pliki z wybranym datasetem bez `mode`', async () => {
    seedDatasets()
    const capture = captureLink()
    const onClose = vi.fn()
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={onClose} />)
    const user = userEvent.setup()

    expect(screen.getByTestId('files-link-confirm')).toBeDisabled()
    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await waitFor(() => expect(screen.getByTestId('files-link-confirm')).toBeEnabled())
    await user.click(screen.getByTestId('files-link-confirm'))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(capture.bodies).toEqual([{ file_ids: ['file-1'], kb_ids: ['ds-1'] }])
    expect(new URL(capture.urls[0]!).searchParams.get('mode')).toBeNull()
    expect(await screen.findByText('Połączono z datasetami.')).toBeInTheDocument()
  })

  it('przełącznik „Dopisuj” dodaje `mode=add` do adresu', async () => {
    seedDatasets()
    const capture = captureLink()
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('files-link-dataset-ds-2'))
    await user.click(screen.getByTestId('files-link-add'))
    await user.click(screen.getByTestId('files-link-confirm'))

    await waitFor(() => expect(capture.urls).toHaveLength(1))
    expect(new URL(capture.urls[0]!).searchParams.get('mode')).toBe('add')
    expect(capture.bodies[0]).toEqual({ file_ids: ['file-1'], kb_ids: ['ds-2'] })
  })

  it('bez datasetów pokazuje komunikat', async () => {
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={() => undefined} />)

    expect(await screen.findByTestId('files-link-empty')).toHaveTextContent(
      'Brak dostępnych datasetów.',
    )
    expect(screen.getByTestId('files-link-confirm')).toBeDisabled()
  })

  it('błąd koperty pokazuje `Alert` i nie zamyka okna', async () => {
    seedDatasets()
    server.use(
      http.post(apiUrl('/api/v1/files/link-to-datasets'), () =>
        HttpResponse.json({ code: 102, message: 'Dataset not found', data: false }),
      ),
    )
    const onClose = vi.fn()
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await user.click(screen.getByTestId('files-link-confirm'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Dataset not found')
    expect(onClose).not.toHaveBeenCalled()
  })

  // SC-V13-13 k3 (T5b): plik nieobsługiwanego typu odrzucony przy „Dodaj do bazy” — ten sam
  // komunikat co w bazie: trasa linku zwraca 102 z tekstem file_suffix (empiria T5b).
  it('błąd nieobsługiwanego typu pliku tłumaczy na PL', async () => {
    seedDatasets()
    server.use(
      http.post(apiUrl('/api/v1/files/link-to-datasets'), () =>
        HttpResponse.json({ code: 102, message: 'file type not supported: setup.exe' }),
      ),
    )
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={() => undefined} />)
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await user.click(screen.getByTestId('files-link-confirm'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nieobsługiwany typ pliku: setup.exe')
    expect(alert).not.toHaveTextContent('file type not supported')
  })

  it('odznaczenie datasetu znów blokuje przycisk', async () => {
    seedDatasets()
    await renderWithProviders(<LinkFilesDialog files={[FILE]} onClose={() => undefined} />)
    const user = userEvent.setup()

    const checkbox = await screen.findByTestId('files-link-dataset-ds-1')
    await user.click(checkbox)
    await waitFor(() => expect(screen.getByTestId('files-link-confirm')).toBeEnabled())
    await user.click(checkbox)

    expect(screen.getByTestId('files-link-confirm')).toBeDisabled()
  })

  it('po ponownym otwarciu czyści wybór i tryb „Dopisuj”', async () => {
    function Harness() {
      const [files, setFiles] = useState<(typeof FILE)[] | null>([FILE])
      return (
        <>
          <button
            type="button"
            data-testid="toggle"
            onClick={() => setFiles(files === null ? [FILE] : null)}
          >
            toggle
          </button>
          <LinkFilesDialog files={files} onClose={() => setFiles(null)} />
        </>
      )
    }

    seedDatasets()
    await renderWithProviders(<Harness />)
    const user = userEvent.setup()

    await user.click(await screen.findByTestId('files-link-dataset-ds-1'))
    await user.click(screen.getByTestId('files-link-add'))
    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(screen.getByTestId('files-link-confirm')).toBeDisabled()
    expect(screen.getByTestId('files-link-add')).not.toBeChecked()
  })
})
