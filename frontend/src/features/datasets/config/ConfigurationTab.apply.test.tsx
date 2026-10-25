/**
 * Testy T6 (WP E5-H8c §2) w zakładce Konfiguracja: podpowiedź „Dotyczy nowych plików” pod trzema
 * polami oraz dialog „Zastosować zmiany do istniejących plików?” po zapisie — warunek otwarcia
 * (≥ 1 dokument), wiersz zmienionych pól, „Tylko nowe pliki” i ścieżka „Zastosuj i parsuj ponownie”.
 * Wydzielone z `ConfigurationTab.test.tsx` przez limit rozmiaru pliku (wzór: `.parser.test.tsx`).
 */

import { HttpResponse, http } from 'msw'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  documentsHandlers,
  fixtureDatasetDetail,
  fixtureDocument,
  fixtureModel,
  modelsHandlers,
} from '../../../test/msw/handlers'
import type { FixtureDatasetDetail } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { Dataset } from '../queries'

import { ConfigurationTab } from './ConfigurationTab'

afterEach(cleanup)

function dataset(overrides: Partial<FixtureDatasetDetail> = {}): Dataset {
  return fixtureDatasetDetail(overrides) as unknown as Dataset
}

function embeddingModels() {
  return modelsHandlers([
    fixtureModel({ model_id: 'embd-1', name: 'fake-embd', model_type: ['embedding'] }),
    fixtureModel({ model_id: 'llm-1', name: 'fake-llm', model_type: ['chat'] }),
    fixtureModel({ model_id: 'vlm-1', name: 'fake-vision', model_type: ['vision'] }),
  ])
}

/** Handlery datasetu (z przechwyceniem PUT) i dokumentów (z licznikiem PATCH dokumentów). */
function setup(item: FixtureDatasetDetail): {
  put: () => Record<string, unknown> | null
  documentPatches: unknown[]
} {
  let updated: Record<string, unknown> | null = null
  const documentPatches: unknown[] = []
  server.use(
    ...datasetHandlers([item], {
      onUpdate: (body) => {
        updated = body
      },
    }),
    ...documentsHandlers(
      [fixtureDocument({ id: 'doc-1', name: 'raport.pdf', parser_config: { pages: [[2, 3]] } })],
      {
        onRequest: (kind, body) => {
          if (kind === 'update') documentPatches.push(body)
        },
      },
    ),
  )
  return { put: () => updated, documentPatches }
}

/** Rejestruje brakującą w atrapach trasę POST `…/chunks` i liczy wywołania. */
function captureChunksPosts(): { count: () => number } {
  let posts = 0
  server.use(
    http.post(apiUrl('/api/v1/datasets/:datasetId/chunks'), () => {
      posts += 1
      return HttpResponse.json({ code: 0, message: 'success', data: null })
    }),
  )
  return { count: () => posts }
}

/** Dataset z zakresem stron 2–3 i parserem w `parser_config` — jak zwraca realny backend. */
function datasetWithPages(): FixtureDatasetDetail {
  return fixtureDatasetDetail({
    parser_config: {
      chunk_token_num: 128,
      delimiter: '\n',
      layout_recognize: 'DeepDOC',
      pages: [[2, 3]],
    },
  })
}

beforeEach(() => {
  server.use(...embeddingModels())
})

describe('ConfigurationTab — zastosowanie do istniejących plików (E5-H8c §2)', () => {
  it('podpowiedź „Dotyczy nowych plików” stoi pod metodą, parserem i zakresem stron', async () => {
    setup(fixtureDatasetDetail())
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    expect(screen.getAllByText(/Dotyczy nowych plików/)).toHaveLength(3)
  })

  it('usunięcie zakresu przy dokumencie otwiera dialog; „Tylko nowe pliki” zamyka bez PATCH', async () => {
    const { put, documentPatches } = setup(datasetWithPages())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset(datasetWithPages())} />)

    await user.click(screen.getByTestId('pages-remove-0'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    const dialog = await screen.findByRole('dialog', {
      name: 'Zastosować zmiany do istniejących plików?',
    })
    expect(within(dialog).getByText('Zmieniono: Zakres stron.')).toBeInTheDocument()
    // Parser NIE zmieniony (ta sama wartość w bazie i łatce) — mimo że łatka niesie cały
    // scalony parser_config, w „Zmieniono:” ma być tylko naprawdę zmienione pole (regresja T6).
    expect(within(dialog).queryByText('Zmieniono: Parser PDF, Zakres stron.')).toBeNull()
    expect(within(dialog).getByText(/Dataset ma 1 plik/)).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }),
    ).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Tylko nowe pliki' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    // Zapis datasetu poszedł (pełny scalony parser_config); dokumenty nietknięte.
    expect(put()).toEqual({
      parser_config: {
        chunk_token_num: 128,
        delimiter: '\n',
        layout_recognize: 'DeepDOC',
        pages: [],
      },
    })
    expect(documentPatches).toEqual([])
  })

  it('zmiana samego opisu nie otwiera dialogu, choć dokumenty są', async () => {
    setup(datasetWithPages())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset(datasetWithPages())} />)

    await user.type(screen.getByLabelText(/Opis/), 'Nowy opis')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('dataset bez dokumentów nie otwiera dialogu mimo zmiany zakresu', async () => {
    setup(datasetWithPages())
    server.use(...documentsHandlers([]))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset(datasetWithPages())} />)

    await user.click(screen.getByTestId('pages-remove-0'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('„Zastosuj i parsuj ponownie” wysyła PATCH dokumentu ze scaloną konfiguracją i jedno POST', async () => {
    const { documentPatches } = setup(datasetWithPages())
    const chunks = captureChunksPosts()
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset(datasetWithPages())} />)

    await user.click(screen.getByTestId('pages-remove-0'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    const dialog = await screen.findByRole('dialog', {
      name: 'Zastosować zmiany do istniejących plików?',
    })
    await user.click(within(dialog).getByRole('button', { name: 'Zastosuj i parsuj ponownie (1)' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    expect(documentPatches).toEqual([{ parser_config: { pages: [] } }])
    expect(chunks.count()).toBe(1)
    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
  })
})
