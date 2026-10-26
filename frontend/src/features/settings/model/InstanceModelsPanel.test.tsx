/**
 * Panel modeli instancji (brief E3-6c1 T6 pkt 1, 2, 5, 6): nagłówek z nazwą, siatka z typami
 * i wymiarem, przełącznik statusu (PATCH), usuwanie z potwierdzeniem, brak akcji u nie-superusera.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  fixtureUser,
  makeInstanceModel,
  makeSeedInstance,
  settingsHandlers,
  toInstanceModel,
  toProviderInstance,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { RenderWithProvidersOptions } from '../../../test/renderWithProviders'
import { stubNarrowViewport } from '../../../test/stubNarrowViewport'

import { InstanceModelsPanel } from './InstanceModelsPanel'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
  vi.unstubAllGlobals()
})

/** Model domyślny instancji — `fake-llm` (blokada wyłączenia i usunięcia). */
const LLM_MODEL = makeInstanceModel({
  name: 'fake-llm',
  model_type: 'chat',
  wd_model_id: 'model-fake-llm',
  wd_is_default: true,
})

/** Instancja z trzema typami modeli; `fake-llm` jest domyślny (blokada wyłączenia). */
const INSTANCE = makeSeedInstance({
  id: 'inst-1',
  name: 'litellm-test',
  models: [
    LLM_MODEL,
    makeInstanceModel({
      name: 'fake-embd',
      model_type: 'embedding',
      wd_model_id: 'model-fake-embd',
      wd_dimension: 768,
    }),
    makeInstanceModel({ name: 'rerank-x', model_type: 'rerank', wd_model_id: 'model-rerank-x' }),
  ],
})

const INSTANCE_REF = toProviderInstance(INSTANCE)
const superuser: Partial<RenderWithProvidersOptions['auth']> = {
  user: { ...fixtureUser, is_superuser: true },
}

/** Render w kontekście trasy `/_app` — stąd `useIsSuperuser` czyta flagę. */
async function renderPanel(
  instance: typeof INSTANCE_REF | null = INSTANCE_REF,
  auth: RenderWithProvidersOptions['auth'] = superuser,
) {
  return renderWithProviders(<InstanceModelsPanel instance={instance} />, {
    route: '/_app',
    routes: ['/_app'],
    auth,
  })
}

/** Wiersz siatki zawierający podaną nazwę modelu. */
function row(name: string): HTMLElement {
  const cell = screen.getByText(name)
  const gridRow = cell.closest('[role="row"]')
  if (gridRow === null) throw new Error(`brak wiersza dla ${name}`)
  return gridRow as HTMLElement
}

describe('InstanceModelsPanel', () => {
  it('pokazuje stan pusty, gdy nie wybrano instancji', async () => {
    await renderPanel(null)

    expect(await screen.findByText('Wybierz instancję')).toBeInTheDocument()
  })

  it('pokazuje nazwę instancji i przyciski zapisu dla superusera', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    await renderPanel()

    expect(
      await screen.findByRole('heading', { name: 'Modele instancji: litellm-test' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dodaj model' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pobierz z /v1/models' })).toBeInTheDocument()
  })

  it('renderuje modele z typem i wymiarem tylko dla embeddingu', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    await renderPanel()

    expect(await screen.findByText('fake-embd')).toBeInTheDocument()
    expect(screen.getByText('Czat')).toBeInTheDocument()
    expect(screen.getByText('Embedding')).toBeInTheDocument()
    expect(within(row('fake-embd')).getByText('768')).toBeInTheDocument()
    expect(within(row('fake-llm')).getByText('—')).toBeInTheDocument()
    // W języku pl wspólny hook `useDataGridLocaleText` ustawia polskie etykiety siatki — stopka
    // paginacji pokazuje „Wierszy na stronę:" (`MuiTablePagination.labelRowsPerPage`) zamiast
    // domyślnego „Rows per page:".
    expect(screen.queryByText('Rows per page:')).not.toBeInTheDocument()
    expect(screen.getByText('Wierszy na stronę:')).toBeInTheDocument()
  })

  it('pokazuje osobne wiersze dla modeli o tej samej nazwie i różnym typie', async () => {
    // Regresja: `getRowId` po samej nazwie mieszał wiersze (chat + vision `gpt`) przy zmianie instancji.
    const twin = makeSeedInstance({
      id: 'inst-2',
      name: 'twin',
      models: [
        makeInstanceModel({ name: 'gpt', model_type: 'chat', wd_model_id: 'm-chat' }),
        makeInstanceModel({ name: 'gpt', model_type: 'vision', wd_model_id: 'm-vision' }),
      ],
    })
    server.use(...settingsHandlers({ instances: [twin] }))
    await renderPanel(toProviderInstance(twin))

    expect(await screen.findAllByText('gpt')).toHaveLength(2)
    expect(screen.getByText('Czat')).toBeInTheDocument()
    expect(screen.getByText('Wizja')).toBeInTheDocument()
  })

  it('wysyła PATCH tylko ze zmianą statusu po przełączeniu modelu', async () => {
    const bodies: { path: string; body: unknown }[] = []
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    server.use(
      http.patch(
        apiUrl('/api/v1/providers/litellm/instances/inst-1/models/:modelName*'),
        async ({ request }) => {
          bodies.push({ path: new URL(request.url).pathname, body: await request.json() })
          return HttpResponse.json({ code: 0, message: 'success' })
        },
      ),
    )
    await renderPanel()

    await screen.findByText('fake-embd')
    await userEvent.setup().click(within(row('fake-embd')).getByRole('switch'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]?.path).toBe('/api/v1/providers/litellm/instances/inst-1/models/fake-embd')
    expect(bodies[0]?.body).toEqual({ status: 'inactive' })
  })

  it('✎ otwiera dialog „Edytuj model” z wartościami z serwera, Anuluj zamyka', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    const user = userEvent.setup()
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Edytuj model fake-embd' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Edytuj model: fake-embd')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Okno kontekstu (tokeny)')).toHaveValue(8192)
    // Embedding: pole współbieżności widoczne i puste (domyślne, SC-E5-H8c-04 krok 1).
    expect(within(dialog).getByLabelText('Równoległe zapytania')).toHaveValue(null)

    await user.click(within(dialog).getByRole('button', { name: 'Anuluj' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('pokazuje Alert 102 przy blokadzie domyślnego modelu, a wiersz zostaje', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    await renderPanel()

    await screen.findByText('fake-llm')
    await userEvent.setup().click(within(row('fake-llm')).getByRole('switch'))

    expect(
      await screen.findByText(
        "Nie udało się wykonać operacji: Model 'fake-llm' is a default model",
      ),
    ).toBeInTheDocument()
    expect(within(row('fake-llm')).getByRole('switch')).toBeChecked()
  })

  it('usuwa model po potwierdzeniu', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    const user = userEvent.setup()
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Usuń model fake-embd' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Usunąć model?')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(screen.queryByText('fake-embd')).toBeNull())
  })

  it('pokazuje Alert 102 przy usunięciu domyślnego modelu, a wiersz zostaje', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    const user = userEvent.setup()
    await renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Usuń model fake-llm' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    expect(
      await screen.findByText(
        "Nie udało się wykonać operacji: Model 'fake-llm' is a default model",
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('fake-llm')).toBeInTheDocument()
  })

  it('nie-superuser widzi siatkę bez akcji zapisu, z wyłączonymi przełącznikami', async () => {
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    await renderPanel(INSTANCE_REF, {})

    await screen.findByText('fake-embd')
    expect(screen.queryByRole('button', { name: 'Dodaj model' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pobierz z /v1/models' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Usuń model fake-embd' })).toBeNull()
    expect(within(row('fake-embd')).getByRole('switch')).toBeDisabled()
  })

  it('błąd listy modeli pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    server.use(
      http.get(apiUrl('/api/v1/providers/litellm/instances/inst-1/models'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 102, message: 'models unavailable' })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: [toInstanceModel(LLM_MODEL)],
        })
      }),
    )
    const user = userEvent.setup()
    await renderPanel()

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wykonać operacji: models unavailable',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('fake-llm')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('na wąskim ekranie akcje są pierwszą kolumną jako menu ⋮', async () => {
    stubNarrowViewport()
    server.use(...settingsHandlers({ instances: [INSTANCE] }))
    await renderPanel()
    await screen.findByText('fake-embd')

    expect(screen.getAllByRole('columnheader')[0]).toHaveAttribute('data-field', 'actions')
    expect(screen.getAllByTestId('row-actions-menu').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Usuń model fake-embd' })).toBeNull()
  })
})
