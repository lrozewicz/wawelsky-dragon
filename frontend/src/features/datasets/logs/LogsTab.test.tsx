/**
 * Zakładka „Logi” (kontrakt WP E3-3a §T5): karty statystyk z `ingestions/summary`, tabela zadań
 * z filtrem statusu i paginacją serwerową, stan pusty, błąd z ponowieniem oraz dialog logu.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  fixtureIngestionLog,
  fixtureIngestionSummary,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { LogsTab } from './LogsTab'

afterEach(cleanup)

const DATASET = fixtureDatasetDetail({
  id: 'ds-1',
  name: 'Alfa',
  document_count: 12,
  chunk_count: 30,
})

const LOG_DONE = fixtureIngestionLog({
  id: 'log-done',
  document_name: 'umowa.pdf',
  operation_status: '3',
  process_duration: 12.5,
})

const LOG_FAILED = fixtureIngestionLog({
  id: 'log-failed',
  document_name: 'raport.pdf',
  operation_status: '4',
  process_duration: 0.4,
})

/** Podsumowanie z jednoznacznymi liczbami (nadpisuje domyślny handler `datasetHandlers`). */
function summaryHandler(
  overrides: Parameters<typeof fixtureIngestionSummary>[0] = {},
): ReturnType<typeof http.get> {
  return http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions/summary'), () =>
    HttpResponse.json({
      code: 0,
      message: 'success',
      data: fixtureIngestionSummary(overrides),
    }),
  )
}

/** Lista zadań zapisująca adresy żądań i filtrująca wiersze po `operation_status`. */
function logsHandler(logs: ReturnType<typeof fixtureIngestionLog>[], seen: URL[]) {
  return http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions'), ({ request }) => {
    const url = new URL(request.url)
    seen.push(url)
    const status = url.searchParams.get('operation_status')
    const matched = logs.filter((log) => status === null || log.operation_status === status)
    return HttpResponse.json({
      code: 0,
      message: 'success',
      data: { logs: matched, total: matched.length },
    })
  })
}

describe('LogsTab', () => {
  it('pokazuje 4 karty statystyk z podsumowania i wiersze zadań', async () => {
    server.use(...datasetHandlers([DATASET], { logs: [LOG_DONE] }))
    server.use(
      summaryHandler({
        doc_num: 12,
        status: {
          cancel_count: 0,
          done_count: 5,
          fail_count: 3,
          running_count: 2,
          unstart_count: 1,
        },
      }),
    )

    await renderWithProviders(<LogsTab datasetId="ds-1" />)

    const all = await screen.findByTestId('logs-stat-all')
    expect(all).toHaveTextContent('Wszystkie pliki')
    expect(all).toHaveTextContent('12')
    expect(screen.getByTestId('logs-stat-queued')).toHaveTextContent('1')
    expect(screen.getByTestId('logs-stat-running')).toHaveTextContent('2')
    expect(screen.getByTestId('logs-stat-failed')).toHaveTextContent('3')

    const file = await screen.findByText('umowa.pdf')
    const row = file.closest('[role="row"]')
    expect(row).not.toBeNull()
    expect(row).toHaveTextContent('log-done')
    expect(row).toHaveTextContent('file')
    expect(row).toHaveTextContent('2025-01-01 00:05:00')
    expect(row).toHaveTextContent('12.5 s')
    expect(row).toHaveTextContent('Sukces')
  })

  it('filtr statusu zawęża wiersze i wysyła operation_status', async () => {
    const seen: URL[] = []
    server.use(...datasetHandlers([DATASET], { logs: [LOG_DONE, LOG_FAILED] }))
    server.use(logsHandler([LOG_DONE, LOG_FAILED], seen))

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<LogsTab datasetId="ds-1" />)

    expect(await screen.findByText('umowa.pdf')).toBeInTheDocument()
    expect(screen.getByText('raport.pdf')).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Błąd' }))

    // Filtr przeładowuje listę asynchronicznie — czekamy na nowy wiersz (`findBy*`), a nie tylko
    // na zniknięcie starego: między refetchami siatka bywa pusta i `getByText` był flakiem.
    await waitFor(() => expect(screen.queryByText('umowa.pdf')).not.toBeInTheDocument())
    expect(await screen.findByText('raport.pdf')).toBeInTheDocument()
    expect(seen.at(-1)?.searchParams.get('operation_status')).toBe('4')
    expect(seen.at(-1)?.searchParams.get('log_type')).toBe('file')
  })

  it('przycisk Log otwiera dialog z komunikatem postępu', async () => {
    const log = fixtureIngestionLog({
      id: 'log-1',
      document_name: 'umowa.pdf',
      operation_status: '1',
      progress_msg: 'Trwa parsowanie strony 3',
    })
    server.use(...datasetHandlers([DATASET], { logs: [log] }))

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<LogsTab datasetId="ds-1" />)

    await user.click(await screen.findByRole('button', { name: 'Pokaż log umowa.pdf' }))

    expect(await screen.findByText('Trwa parsowanie strony 3')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('umowa.pdf')
  })

  it('brak zadań pokazuje stan pusty siatki', async () => {
    server.use(...datasetHandlers([DATASET], { logs: [] }))

    await renderWithProviders(<LogsTab datasetId="ds-1" />)

    expect(await screen.findByTestId('empty-state')).toHaveTextContent('Brak zadań')
  })

  it('błąd listy pokazuje Alert, a „Spróbuj ponownie” wraca do danych', async () => {
    let calls = 0
    server.use(...datasetHandlers([DATASET], { logs: [LOG_DONE] }))
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/ingestions'), () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 101, message: 'boom', data: null })
          : HttpResponse.json({ code: 0, message: 'success', data: { logs: [LOG_DONE], total: 1 } })
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<LogsTab datasetId="ds-1" />)

    const alert = await screen.findByTestId('query-error')
    expect(alert).toHaveTextContent('Nie udało się wczytać zadań.')

    await user.click(within(alert).getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('umowa.pdf')).toBeInTheDocument()
  })

  it('w języku polskim używa lokalizacji plPL siatki', async () => {
    server.use(...datasetHandlers([DATASET], { logs: [LOG_DONE] }))

    await renderWithProviders(<LogsTab datasetId="ds-1" />)
    await screen.findByText('umowa.pdf')

    expect(screen.getByText('Wierszy na stronę:')).toBeInTheDocument()
  })

  it('w języku angielskim zostaje przy domyślnej lokalizacji siatki', async () => {
    server.use(...datasetHandlers([DATASET], { logs: [] }))

    await renderWithProviders(<LogsTab datasetId="ds-1" />, { language: 'en' })

    expect(await screen.findByTestId('empty-state')).toHaveTextContent('No tasks')
    expect(screen.getByText('Rows per page:')).toBeInTheDocument()
  })
})
