/**
 * Karta „Modele domyślne” (brief E3-6c1 T5a): bieżące modele z `GET /api/v1/users/me/models`,
 * opcje filtrowane po `model_type` z `GET /api/v1/models`, zapis przez
 * `PATCH /api/v1/users/me/models` tylko dla superusera, odczyt dla pozostałych.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import type { AuthState } from '../../auth/authState'
import {
  apiUrl,
  fixtureModels,
  fixtureUser,
  makeInstanceModel,
  makeSeedInstance,
  settingsHandlers,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DefaultModelsCard } from './DefaultModelsCard'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

/** Zalogowany superuser — karta dostaje przycisk Zapisz i aktywne selecty. */
const authSuperuser: Partial<AuthState> = {
  user: { ...fixtureUser, is_superuser: true },
}

/** Instancja z rejestrem modeli wszystkich czterech typów (rejestr liczy się z instancji). */
function seedInstance() {
  return makeSeedInstance({
    models: [
      makeInstanceModel({ name: 'fake-llm', model_type: 'chat', wd_model_id: 'model-fake-llm' }),
      makeInstanceModel({
        name: 'fake-embd',
        model_type: 'embedding',
        wd_model_id: 'model-fake-embd',
        wd_dimension: 8,
      }),
      makeInstanceModel({ name: 'gpt-x', model_type: 'chat', wd_model_id: 'model-gpt-x' }),
      makeInstanceModel({ name: 'rerank-x', model_type: 'rerank', wd_model_id: 'model-rerank-x' }),
      makeInstanceModel({ name: 'vlm-x', model_type: 'vision', wd_model_id: 'model-vlm-x' }),
    ],
  })
}

/**
 * Render karty. Kontrakt trasy `/_app` (skąd `useIsSuperuser` czyta flagę) — testowy router
 * `renderWithProviders` tworzy trasy wyłącznie z opcji `route`/`routes`, więc rejestrujemy `/_app`
 * i startujemy na tej ścieżce; korzeń renderuje badaną kartę.
 */
async function renderCard(auth?: Partial<AuthState>, instance = seedInstance()) {
  server.use(...settingsHandlers({ instances: [instance] }))
  return renderWithProviders(<DefaultModelsCard />, {
    route: '/_app',
    routes: ['/_app'],
    auth,
  })
}

/** Rozwija sekcję ADV, w której mieszka select VLM. */
async function expandAdvanced(): Promise<void> {
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Zaawansowane' }))
}

/** PATCH modeli domyślnych: przechwytuje ciała i zwraca sukces bez `data`. */
function capturePatch(bodies: unknown[]) {
  return http.patch(apiUrl('/api/v1/users/me/models'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success', data: null })
  })
}

/** Otwiera select po `data-testid` i klika opcję po nazwie. */
async function chooseOption(testId: string, option: string): Promise<void> {
  const user = userEvent.setup()
  const field = await screen.findByTestId(testId)
  await user.click(within(field).getByRole('combobox'))
  await user.click(await screen.findByRole('option', { name: option }))
}

describe('DefaultModelsCard', () => {
  it('pokazuje bieżące modele domyślne, a puste Rerank/VLM jako „Brak”', async () => {
    await renderCard(authSuperuser)

    expect(await screen.findByRole('heading', { name: 'Modele domyślne' })).toBeInTheDocument()
    expect(screen.getByTestId('defaults-llm')).toHaveTextContent('fake-llm')
    expect(screen.getByTestId('defaults-embedding')).toHaveTextContent('fake-embd')
    expect(screen.getByTestId('defaults-rerank')).toHaveTextContent('Brak')
    expect(screen.getByTestId('defaults-vlm')).toHaveTextContent('Brak')
  })

  it('oznacza LLM i Embedding gwiazdką, a Rerank nie', async () => {
    await renderCard(authSuperuser)
    await screen.findByTestId('defaults-llm')

    expect(screen.getByTestId('defaults-llm')).toHaveTextContent('*')
    expect(screen.getByTestId('defaults-embedding')).toHaveTextContent('*')
    expect(screen.getByTestId('defaults-rerank')).not.toHaveTextContent('*')
  })

  it('zawęża opcje selecta po typie modelu z rejestru', async () => {
    await renderCard(authSuperuser)
    await screen.findByTestId('defaults-llm')
    const user = userEvent.setup()

    await user.click(within(screen.getByTestId('defaults-llm')).getByRole('combobox'))
    expect(await screen.findByRole('option', { name: 'gpt-x' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'rerank-x' })).toBeNull()
    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('option', { name: 'gpt-x' })).toBeNull())

    await user.click(within(screen.getByTestId('defaults-rerank')).getByRole('combobox'))
    expect(await screen.findByRole('option', { name: 'rerank-x' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'gpt-x' })).toBeNull()
  })

  it('wysyła tylko zmienione i niepuste pole: LLM na `gpt-x` daje `{"llm_id":"gpt-x"}`', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderCard(authSuperuser)

    await chooseOption('defaults-llm', 'gpt-x')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ llm_id: 'gpt-x' })
    expect(await screen.findByText('Zapisano modele domyślne')).toBeInTheDocument()
  })

  it('wysyła zmianę VLM jako `img2txt_id`', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderCard(authSuperuser)

    await expandAdvanced()
    await chooseOption('defaults-vlm', 'vlm-x')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ img2txt_id: 'vlm-x' })
  })

  it('przyjmuje oba oznaczenia modelu wizji: `vision` i `image2text`', async () => {
    const instance = makeSeedInstance({
      models: [
        makeInstanceModel({
          name: 'vlm-vision',
          model_type: 'vision',
          wd_model_id: 'model-vlm-vision',
        }),
        makeInstanceModel({
          name: 'vlm-image2text',
          model_type: 'image2text',
          wd_model_id: 'model-vlm-image2text',
        }),
      ],
    })
    await renderCard(authSuperuser, instance)

    await expandAdvanced()
    await userEvent.setup().click(within(screen.getByTestId('defaults-vlm')).getByRole('combobox'))

    expect(await screen.findByRole('option', { name: 'vlm-vision' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'vlm-image2text' })).toBeInTheDocument()
  })

  it('blokuje przycisk Zapisz, gdy nic się nie zmieniło', async () => {
    await renderCard(authSuperuser)

    expect(await screen.findByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('pokazuje błąd zapisu jako `Alert` z nagłówkiem i komunikatem API', async () => {
    server.use(
      http.patch(apiUrl('/api/v1/users/me/models'), () =>
        HttpResponse.json({ code: 102, message: 'model not found', data: null }),
      ),
    )
    await renderCard(authSuperuser)

    await chooseOption('defaults-llm', 'gpt-x')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Zapisz' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nie udało się wykonać operacji: model not found')
  })

  it('zwykły użytkownik widzi selecty bez zapisu i komunikat o odczycie', async () => {
    await renderCard()

    expect(
      await screen.findByText('Tylko superużytkownik może zmieniać te ustawienia.'),
    ).toBeInTheDocument()
    expect(within(screen.getByTestId('defaults-llm')).getByRole('combobox')).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.queryByRole('button', { name: 'Zapisz' })).toBeNull()
  })

  it('pokazuje `Skeleton`, dopóki dane się ładują', async () => {
    server.use(
      http.get(apiUrl('/api/v1/users/me/models'), async () => {
        await delay(50)
        return HttpResponse.json({ code: 0, message: 'success', data: fixtureModels })
      }),
    )
    await renderCard(authSuperuser)

    expect(screen.getByTestId('defaults-loading')).toBeInTheDocument()
    expect(await screen.findByTestId('defaults-llm')).toBeInTheDocument()
  })

  it('pokazuje `Alert` z komunikatem API, gdy odczyt się nie powiedzie', async () => {
    server.use(
      http.get(apiUrl('/api/v1/users/me/models'), () =>
        HttpResponse.json({ code: 102, message: 'models unavailable', data: null }),
      ),
    )
    await renderCard(authSuperuser)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nie udało się wykonać operacji: models unavailable')
  })
})
