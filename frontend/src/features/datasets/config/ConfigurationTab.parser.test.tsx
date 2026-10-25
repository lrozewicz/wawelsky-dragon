/**
 * Select parsera PDF i edytor zakresu stron w konfiguracji datasetu (kontrakt E5-H3 §#9), wydzielone
 * z `ConfigurationTab.test.tsx` przez limit rozmiaru pliku: opcje z modeli image2text, wartość
 * spoza listy (stare `VLM`) jako „nieznany model", zapis `parser_config.pages` i jego walidacja.
 */

import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  datasetHandlers,
  fixtureDatasetDetail,
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
    // Model wizji: realne API zwraca image2text jako `vision` (routes/models.py:35).
    fixtureModel({ model_id: 'vlm-1', name: 'fake-vision', model_type: ['vision'] }),
  ])
}

/** Podmienia handlery datasetu i przechwytuje ciało PUT-a. */
function captureUpdate(item: FixtureDatasetDetail): { body: () => Record<string, unknown> | null } {
  let updated: Record<string, unknown> | null = null
  server.use(
    ...datasetHandlers([item], {
      onUpdate: (body) => {
        updated = body
      },
    }),
  )
  return { body: () => updated }
}

/** Otwiera select parsera PDF po `data-testid` (wzór `AddModelDialog.test`). */
async function openParserSelect(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const field = screen.getByTestId('pdf-parser-select')
  await user.click(within(field).getByRole('combobox'))
}

beforeEach(() => {
  server.use(...embeddingModels())
})

describe('ConfigurationTab — parser PDF i zakres stron', () => {
  it('select parsera PDF pokazuje modele wizji z rejestru', async () => {
    captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await openParserSelect(user)

    expect(await screen.findByRole('option', { name: 'fake-vision' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Auto' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Tylko tekst' })).toBeInTheDocument()
  })

  it('model wizji oznaczony backendowym `image2text` też trafia do opcji', async () => {
    server.use(
      ...modelsHandlers([
        fixtureModel({ model_id: 'vlm-2', name: 'vlm-image2text', model_type: ['image2text'] }),
      ]),
    )
    captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await openParserSelect(user)

    expect(await screen.findByRole('option', { name: 'vlm-image2text' })).toBeInTheDocument()
  })

  it('nieznany parser (VLM) pokazuje opcję „nieznany model”, błąd od wczytania i PUT po kliku nie wychodzi', async () => {
    const captured = captureUpdate(
      fixtureDatasetDetail({
        parser_config: { layout_recognize: 'VLM', chunk_token_num: 128, delimiter: '\n' },
      }),
    )
    const user = userEvent.setup()
    await renderWithProviders(
      <ConfigurationTab
        dataset={dataset({
          parser_config: { layout_recognize: 'VLM', chunk_token_num: 128, delimiter: '\n' },
        })}
      />,
    )

    expect(screen.getByTestId('pdf-parser-select')).toHaveTextContent(
      'Nieznany model — wybierz model',
    )
    expect(
      await screen.findByText('Wybrany model parsera jest nieznany — wybierz model z listy.'),
    ).toBeInTheDocument()

    await openParserSelect(user)
    expect(screen.getByRole('option', { name: 'Nieznany model — wybierz model' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    await user.keyboard('{Escape}')

    // U11: przycisk nie bywa wyłączony przez błąd — klik go ujawnia (tu: od wczytania),
    // wraca fokusem do selekta parsera i PUT nie wychodzi.
    await user.type(screen.getByLabelText(/Nazwa/), ' X')
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    expect(within(screen.getByTestId('pdf-parser-select')).getByRole('combobox')).toHaveFocus()
    expect(captured.body()).toBeNull()
  })

  it('zapisuje model wizji i zakres stron do parser_config', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await openParserSelect(user)
    await user.click(await screen.findByRole('option', { name: 'fake-vision' }))

    await user.click(screen.getByTestId('pages-add'))
    fireEvent.change(screen.getByTestId('pages-from-0'), { target: { value: '2' } })
    fireEvent.change(screen.getByTestId('pages-to-0'), { target: { value: '2' } })

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({
        parser_config: {
          chunk_token_num: 128,
          delimiter: '\n',
          layout_recognize: 'fake-vision',
          pages: [[2, 2]],
        },
      })
    })
    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
  })

  it('nakładające się zakresy pokazują błąd; klik „Zapisz” nie wysyła PUT-u (U11)', async () => {
    const captured = captureUpdate(
      fixtureDatasetDetail({
        parser_config: {
          pages: [
            [1, 4],
            [3, 6],
          ],
        },
      }),
    )
    const user = userEvent.setup()
    await renderWithProviders(
      <ConfigurationTab
        dataset={dataset({
          parser_config: {
            pages: [
              [1, 4],
              [3, 6],
            ],
          },
        })}
      />,
    )

    expect(await screen.findByText('Zakresy stron nie mogą się nakładać.')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/Nazwa/), ' X')
    // U11: przycisk aktywny mimo błędu; klik nie wysyła łatki (pierwszy błąd: zakresy).
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    expect(captured.body()).toBeNull()
  })

  it('usunięcie zakresu czyści `pages` w zapisie', async () => {
    const captured = captureUpdate(
      fixtureDatasetDetail({ parser_config: { chunk_token_num: 128, pages: [[2, 2]] } }),
    )
    const user = userEvent.setup()
    await renderWithProviders(
      <ConfigurationTab
        dataset={dataset({ parser_config: { chunk_token_num: 128, pages: [[2, 2]] } })}
      />,
    )

    expect(screen.getByTestId('pages-from-0')).toHaveValue(2)
    await user.click(screen.getByTestId('pages-remove-0'))
    expect(screen.queryByTestId('pages-from-0')).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({ parser_config: { chunk_token_num: 128, pages: [] } })
    })
  })

  it('Dodaj zakres daje pusty wiersz z fokusem w „Od” (SC-E5-H9-05)', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.click(screen.getByTestId('pages-add'))

    // Wiersz startuje PUSTY (nie „1-1”), fokus w polu „Od”.
    expect(screen.getByTestId('pages-from-0')).toHaveValue(null)
    expect(screen.getByTestId('pages-to-0')).toHaveValue(null)
    expect(screen.getByTestId('pages-from-0')).toHaveFocus()

    // Półpełny wiersz dostaje komunikat przy edytorze; „Zapisz” wyłącza brak zmian
    // (niepełny wiersz nie tworzy łatki), a nie błąd walidacji (U11).
    fireEvent.change(screen.getByTestId('pages-from-0'), { target: { value: '2' } })
    expect(screen.getByText('Uzupełnij oba pola zakresu albo usuń wiersz.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()

    // Całkiem pusty wiersz po usunięciu zostawia formularz bez zmian (łatka pusta).
    await user.click(screen.getByTestId('pages-remove-0'))
  })

  it('niewypełniony wiersz zakresu nie zmienia łatki zapisu', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.click(screen.getByTestId('pages-add'))
    fireEvent.change(screen.getByTestId('pages-from-0'), { target: { value: '2' } })
    fireEvent.change(screen.getByTestId('pages-to-0'), { target: { value: '2' } })
    await user.click(screen.getByTestId('pages-add'))

    // Drugi wiersz pusty: zapis wysyła wyłącznie pełny zakres.
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    await waitFor(() => {
      expect(captured.body()).toEqual({
        parser_config: { chunk_token_num: 128, delimiter: '\n', pages: [[2, 2]] },
      })
    })
  })
})
