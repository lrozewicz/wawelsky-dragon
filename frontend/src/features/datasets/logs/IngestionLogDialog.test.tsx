/**
 * Dialog logu zadania (kontrakt WP E3-3a §T5): plik, status, czas i preformatowany `progress_msg`.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  fixtureIngestionLog,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { IngestionLogDialog } from './IngestionLogDialog'

afterEach(cleanup)

const DATASET = fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa' })

describe('IngestionLogDialog', () => {
  it('pokazuje plik, status, czas i treść logu w bloku pre', async () => {
    const log = fixtureIngestionLog({
      id: 'log-1',
      document_name: 'umowa.pdf',
      operation_status: '1',
      process_duration: 3.25,
      progress_msg: 'Trwa parsowanie strony 3',
    })
    server.use(...datasetHandlers([DATASET], { logs: [log] }))

    await renderWithProviders(
      <IngestionLogDialog datasetId="ds-1" logId="log-1" onClose={() => {}} />,
    )

    const message = await screen.findByText('Trwa parsowanie strony 3')
    expect(message.tagName).toBe('PRE')
    expect(screen.getByRole('dialog')).toHaveTextContent('umowa.pdf')
    expect(screen.getByRole('dialog')).toHaveTextContent('Parsowanie')
    expect(screen.getByRole('dialog')).toHaveTextContent('3.3 s')
  })

  it('tłumaczy wpisy P1–P29 jak ProcessLogDialog (T10, QA D2a), nieznane zostają dosłownie', async () => {
    const log = fixtureIngestionLog({
      id: 'log-2',
      progress_msg:
        '08:00:01 Task has been received.\n08:00:02 Auto metadata: 0 fields\ncałkiem nieznany wpis 42',
    })
    server.use(...datasetHandlers([DATASET], { logs: [log] }))

    await renderWithProviders(
      <IngestionLogDialog datasetId="ds-1" logId="log-2" onClose={() => {}} />,
    )

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('08:00:01 Zadanie przyjęte.')
    expect(dialog).toHaveTextContent('Metadane automatyczne: nie znaleziono wartości')
    expect(dialog).toHaveTextContent('całkiem nieznany wpis 42')
    expect(dialog).not.toHaveTextContent('Task has been received.')
    expect(dialog).not.toHaveTextContent('Auto metadata: 0 fields')
  })

  it('nieznany kod statusu pokazuje surową wartość, a Zamknij woła onClose', async () => {
    const log = fixtureIngestionLog({ id: 'log-9', operation_status: 'nieznany' })
    server.use(...datasetHandlers([DATASET], { logs: [log] }))
    const onClose = vi.fn()

    const user = userEvent.setup()
    await renderWithProviders(
      <IngestionLogDialog datasetId="ds-1" logId="log-9" onClose={onClose} />,
    )

    expect(await screen.findByText('nieznany')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('błąd pobrania logu pokazuje Alert', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/:logId'), () =>
        HttpResponse.json({ code: 102, message: 'Log not found', data: null }),
      ),
    )

    await renderWithProviders(
      <IngestionLogDialog datasetId="ds-1" logId="brak" onClose={() => {}} />,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać logu.')
  })
})
