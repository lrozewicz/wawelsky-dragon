import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
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

/** Atrapa MSW to podzbiór `DatasetDetail` — zakładka czyta z niej pola z kontraktu §T4. */
function dataset(overrides: Partial<FixtureDatasetDetail> = {}): Dataset {
  return fixtureDatasetDetail(overrides) as unknown as Dataset
}

function embeddingModels() {
  return modelsHandlers([
    fixtureModel({ model_id: 'embd-1', name: 'fake-embd', model_type: ['embedding'] }),
    fixtureModel({ model_id: 'embd-2', name: 'other-embd', model_type: ['embedding'] }),
    fixtureModel({ model_id: 'llm-1', name: 'fake-llm', model_type: ['chat'] }),
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

beforeEach(() => {
  server.use(...embeddingModels())
})

describe('ConfigurationTab', () => {
  it('zmiana nazwy wysyła PUT tylko z nazwą i pokazuje „Zapisano”', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()

    const name = screen.getByLabelText(/Nazwa/)
    await user.clear(name)
    await user.type(name, 'Nowa nazwa')
    expect(save).toBeEnabled()

    await user.click(save)

    await waitFor(() => {
      expect(captured.body()).toEqual({ name: 'Nowa nazwa' })
    })
    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    // Po sukcesie bazą formularza jest zwrócony dataset — nie ma już czego zapisywać.
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('blokuje model embeddingu przy istniejących chunkach i pokazuje wyjaśnienie', async () => {
    captureUpdate(fixtureDatasetDetail({ chunk_count: 12 }))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset({ chunk_count: 12 })} />)

    const embedding = screen.getByRole('combobox', { name: 'Model embeddingu' })
    expect(embedding).toBeDisabled()

    await user.hover(embedding)
    expect(
      await screen.findByText('Modelu embeddingu nie można zmienić, gdy baza ma już chunki.'),
    ).toBeInTheDocument()
  })

  it('przy zerze chunków odblokowuje model embeddingu', async () => {
    captureUpdate(fixtureDatasetDetail({ chunk_count: 0 }))
    await renderWithProviders(<ConfigurationTab dataset={dataset({ chunk_count: 0 })} />)

    expect(screen.getByRole('combobox', { name: 'Model embeddingu' })).toBeEnabled()
  })

  it('zmiana metody przy chunkach zapisuje od razu; dialog pojawia się dopiero przy dokumentach', async () => {
    // Brak dokumentów w atrapie MSW → po zapisie nie ma pytać o istniejące pliki (kontrakt §2).
    const captured = captureUpdate(fixtureDatasetDetail({ chunk_count: 12 }))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset({ chunk_count: 12 })} />)

    await user.click(screen.getByRole('combobox', { name: 'Metoda chunkowania' }))
    await user.click(await screen.findByRole('option', { name: 'Q&A' }))
    // Karta po prawej opisuje wybraną metodę.
    expect(screen.getByText(/pary pytanie–odpowiedź/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    await waitFor(() => {
      expect(captured.body()).toEqual({ chunk_method: 'qa' })
    })
    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('bez chunków zmiana metody nie wymaga potwierdzenia', async () => {
    const captured = captureUpdate(fixtureDatasetDetail({ chunk_count: 0 }))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset({ chunk_count: 0 })} />)

    await user.click(screen.getByRole('combobox', { name: 'Metoda chunkowania' }))
    await user.click(await screen.findByRole('option', { name: 'One' }))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({ chunk_method: 'one' })
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('parser PDF, rozmiar chunku i separator trafiają do parser_config', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.click(screen.getByRole('combobox', { name: 'Parser PDF' }))
    await user.click(await screen.findByRole('option', { name: 'Tylko tekst' }))
    screen.getByRole('slider', { name: 'Rekomendowany rozmiar chunku (tokeny)' }).focus()
    await user.keyboard('{ArrowRight}')
    const delimiter = screen.getByLabelText(/Separator tekstu/)
    await user.clear(delimiter)
    await user.type(delimiter, ';')

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({
        parser_config: {
          chunk_token_num: 129,
          delimiter: ';',
          layout_recognize: 'Plain Text',
        },
      })
    })
  })

  it('zmienia model embeddingu przy bazie bez chunków', async () => {
    const captured = captureUpdate(fixtureDatasetDetail({ chunk_count: 0 }))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset({ chunk_count: 0 })} />)

    await user.click(screen.getByRole('combobox', { name: 'Model embeddingu' }))
    await user.click(await screen.findByRole('option', { name: 'other-embd' }))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({ embedding_model: 'embd-2' })
    })
  })

  it('U11: pusta nazwa nie wyłącza „Zapisz”; klik ujawnia „Pole wymagane” i wraca fokusem', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.clear(screen.getByLabelText(/Nazwa/))
    // W trakcie pisania komunikatu nie ma, a przycisk zostaje aktywny (jest zmiana = dirty).
    expect(screen.queryByText('Pole wymagane')).toBeNull()
    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeEnabled()

    await user.click(save)
    expect(await screen.findByText('Pole wymagane')).toBeInTheDocument()
    expect(screen.getByLabelText(/Nazwa/)).toHaveFocus()
    expect(captured.body()).toBeNull()

    // Wpisanie wartości gasi komunikat od razu (SC-E5-H9-02 krok 3).
    await user.type(screen.getByLabelText(/Nazwa/), 'Nowa nazwa')
    expect(screen.queryByText('Pole wymagane')).toBeNull()
  })

  it('U11: zbyt długi opis pokazuje błąd po opuszczeniu pola; „Zapisz” zostaje aktywne', async () => {
    captureUpdate(fixtureDatasetDetail())
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    const description = screen.getByLabelText(/Opis/)
    fireEvent.change(description, { target: { value: 'x'.repeat(513) } })
    expect(screen.queryByText('Opis może mieć maksymalnie 512 znaków.')).toBeNull()

    fireEvent.blur(description)
    expect(await screen.findByText('Opis może mieć maksymalnie 512 znaków.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
  })

  it('Anuluj przywraca wartości początkowe bez wysyłki', async () => {
    const captured = captureUpdate(fixtureDatasetDetail())
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    const name = screen.getByLabelText(/Nazwa/)
    await user.clear(name)
    await user.type(name, 'Inna nazwa')
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(screen.getByLabelText(/Nazwa/)).toHaveValue('Baza testowa')
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
    expect(captured.body()).toBeNull()
  })

  it('baza bez modelu embeddingu wypełnia formularz pustym polem', async () => {
    captureUpdate(fixtureDatasetDetail({ embedding_model: '' }))
    await renderWithProviders(<ConfigurationTab dataset={dataset({ embedding_model: '' })} />)

    expect(screen.getByRole('combobox', { name: 'Model embeddingu' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('błąd transportu pokazuje komunikat z i18n', async () => {
    server.use(http.put(apiUrl('/api/v1/datasets/:datasetId'), () => HttpResponse.error()))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.clear(screen.getByLabelText(/Nazwa/))
    await user.type(screen.getByLabelText(/Nazwa/), 'Nowa nazwa')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nie udało się zapisać konfiguracji.',
    )
  })

  it('błąd API ląduje w `Alert`, a formularz zostaje wypełniony', async () => {
    // Backend odmawia zmiany (np. brak uprawnień) — odpowiedź z kodem błędu w kopercie.
    server.use(
      http.put(apiUrl('/api/v1/datasets/:datasetId'), () =>
        HttpResponse.json({ code: 109, message: 'Odmowa', data: null }),
      ),
    )
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await user.clear(screen.getByLabelText(/Nazwa/))
    await user.type(screen.getByLabelText(/Nazwa/), 'Nowa nazwa')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Odmowa')
    expect(screen.getByLabelText(/Nazwa/)).toHaveValue('Nowa nazwa')
  })
})
