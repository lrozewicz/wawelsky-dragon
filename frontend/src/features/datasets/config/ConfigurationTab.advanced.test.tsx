/**
 * Sekcja „Zaawansowane” formularza konfiguracji (08 §8.1) — wydzielona z
 * `ConfigurationTab.test.tsx` przez limit rozmiaru pliku: akordeon renderuje pola dopiero
 * po rozwinięciu (`unmountOnExit`), a ich wartości rozdzielają się między pola top-level
 * (`language`, `permission`) i `parser_config`.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
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

beforeEach(() => {
  server.use(
    ...modelsHandlers([
      fixtureModel({ model_id: 'embd-1', name: 'fake-embd', model_type: ['embedding'] }),
      fixtureModel({ model_id: 'llm-1', name: 'fake-llm', model_type: ['chat'] }),
    ]),
  )
})

describe('ConfigurationTab — Zaawansowane', () => {
  it('pola „Zaawansowane” są poza DOM do rozwinięcia akordeonu', async () => {
    captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    expect(screen.queryByLabelText('Język')).toBeNull()
    expect(screen.queryByText('Nakładanie (%)')).toBeNull()

    await user.click(screen.getByText('Zaawansowane'))

    expect(await screen.findByLabelText('Język')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Zespół' })).toBeInTheDocument()
    expect(screen.getByText(/Nakładanie \(%\)/)).toBeInTheDocument()
  })

  it('pola „Zaawansowane” rozdziela między top-level i parser_config', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.click(screen.getByText('Zaawansowane'))
    await user.click(await screen.findByRole('combobox', { name: 'Język' }))
    await user.click(await screen.findByRole('option', { name: 'English' }))
    await user.click(screen.getByRole('radio', { name: 'Zespół' }))
    // Powrót na „Tylko ja” (i znów na „Zespół”) sprawdza oba warianty przełącznika uprawnień.
    await user.click(screen.getByRole('radio', { name: 'Tylko ja' }))
    await user.click(screen.getByRole('radio', { name: 'Zespół' }))
    await user.click(screen.getByRole('switch', { name: 'Excel jako HTML' }))
    await user.click(screen.getByRole('combobox', { name: 'Model indeksujący' }))
    await user.click(await screen.findByRole('option', { name: 'fake-llm' }))
    // Suwak nakładania: +1 przez strzałkę (0 → 1).
    screen.getByRole('slider', { name: 'Nakładanie (%)' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByText('Nakładanie (%): 1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({
        language: 'English',
        permission: 'team',
        parser_config: {
          chunk_token_num: 128,
          delimiter: '\n',
          overlapped_percent: 1,
          html4excel: true,
          llm_id: 'fake-llm',
        },
      })
    })
  })

  it('wyczyszczenie modelu indeksującego wraca do stanu początkowego', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.click(screen.getByText('Zaawansowane'))
    await user.click(await screen.findByRole('combobox', { name: 'Model indeksujący' }))
    await user.click(await screen.findByRole('option', { name: 'fake-llm' }))
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

    await user.click(screen.getByTitle('Clear'))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
    })
    expect(captured.body()).toBeNull()
  })
})
