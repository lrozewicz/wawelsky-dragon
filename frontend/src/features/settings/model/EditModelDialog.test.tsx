/**
 * Dialog „Edytuj model” (brief E5-H8c T3, kontrakt WP E5-H8c §1): walidacja pól, ciało PATCH
 * z PEŁNYM `extra` (K13 „Poprawka 2026-10-10”), pole współbieżności tylko dla vision/embedding.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, makeInstanceModel, toInstanceModel } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { InstanceModel } from '../providerQueries'

import { EditModelDialog, formFromModel } from './EditModelDialog'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

const MODELS_URL = apiUrl('/api/v1/providers/litellm/instances/inst-1/models')

/** Przechwytuje ciała `PATCH …/models/:name` i zwraca sukces. */
function capturePatch(bodies: unknown[]) {
  return http.patch(`${MODELS_URL}/:modelName*`, async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success', data: null })
  })
}

/** Odpowiedź 500 — treść błędu ma trafić do `Alert` w dialogu. */
function failingPatch() {
  return http.patch(`${MODELS_URL}/:modelName*`, () =>
    HttpResponse.json({ code: 500, message: 'E2E: symulowana awaria zapisu' }),
  )
}

function model(overrides: Partial<InstanceModel> = {}): InstanceModel {
  return toInstanceModel(
    makeInstanceModel({
      name: 'fake-ocr',
      model_type: 'image2text',
      max_tokens: 4096,
      extra: { supports_reasoning: true, max_concurrency: 3 },
      ...overrides,
    }),
  )
}

async function renderDialog(props: { model: InstanceModel; open?: boolean; onClose?: () => void }) {
  const onClose = vi.fn()
  const result = await renderWithProviders(
    <EditModelDialog
      instanceId="inst-1"
      open={props.open ?? true}
      model={props.model}
      onClose={onClose}
    />,
  )
  return { ...result, onClose }
}

describe('EditModelDialog', () => {
  it('pokazuje wartości z serwera: max_tokens i nie-domyślną współbieżność', async () => {
    await renderDialog({
      model: model({ extra: { supports_reasoning: true, max_concurrency: 24 } }),
    })

    expect(screen.getByText('Edytuj model: fake-ocr')).toBeInTheDocument()
    expect(screen.getByLabelText('Okno kontekstu (tokeny)')).toHaveValue(4096)
    expect(screen.getByLabelText('Równoległe zapytania')).toHaveValue(24)
    expect(screen.getByText('Typ: Wizja (nie można zmienić)')).toBeInTheDocument()
  })

  it('współbieżność równa domyślnej: pole puste z podpowiedzią „domyślnie 3”', async () => {
    await renderDialog({ model: model() })

    const field = screen.getByLabelText('Równoległe zapytania')
    expect(field).toHaveValue(null)
    expect(field).toHaveAttribute('placeholder', 'domyślnie 3')
  })

  it('wysyła PATCH z pełnym extra (podmienione max_concurrency) i zamyka dialog', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const { onClose } = await renderDialog({ model: model() })
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '128000')
    await user.type(screen.getByLabelText('Równoległe zapytania'), '24')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      max_tokens: 128000,
      extra: { supports_reasoning: true, max_concurrency: 24 },
    })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('wyczyszczenie pola usuwa max_concurrency, pozostałe klucze extra zostają', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDialog({ model: model() })
    const user = userEvent.setup()

    await user.clear(screen.getByLabelText('Równoległe zapytania'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ max_tokens: 4096, extra: { supports_reasoning: true } })
  })

  it('model czatu: pola współbieżności nie ma, a extra zostaje bez zmian', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDialog({
      model: model({
        name: 'fake-chat',
        model_type: 'chat',
        extra: { extra_body: { a: 1 } },
      }),
    })
    const user = userEvent.setup()

    expect(screen.queryByLabelText('Równoległe zapytania')).toBeNull()
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '100000')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ max_tokens: 100000, extra: { extra_body: { a: 1 } } })
  })

  it('walidacja: 100 → „Co najmniej 1024”, 40 → „Wartość od 1 do 32”, Zapisz nieaktywny', async () => {
    await renderDialog({ model: model() })
    const user = userEvent.setup()
    const save = screen.getByRole('button', { name: 'Zapisz' })

    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '100')
    expect(screen.getByText('Co najmniej 1024')).toBeInTheDocument()
    expect(save).toBeDisabled()

    await user.type(screen.getByLabelText('Równoległe zapytania'), '40')
    expect(screen.getByText('Wartość od 1 do 32')).toBeInTheDocument()
    expect(save).toBeDisabled()

    await user.clear(screen.getByLabelText('Równoległe zapytania'))
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '1024')
    expect(save).toBeEnabled()
  })

  it('SC-V12-08: nieaktywny „Zapisz” ma powód z aria-describedby, który znika po poprawie', async () => {
    await renderDialog({ model: model() })
    const user = userEvent.setup()
    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeEnabled()

    // Puste wymagane pole → „Uzupełnij: …”; błędna wartość → „Popraw: …”.
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'edit-model-save-reason')
    expect(screen.getByText('Uzupełnij: Okno kontekstu (tokeny)')).toHaveAttribute(
      'id',
      'edit-model-save-reason',
    )

    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '100')
    expect(screen.getByText('Popraw: Okno kontekstu (tokeny)')).toBeInTheDocument()

    // Poprawa → powód i atrybut znikają, przycisk aktywny.
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '4096')
    expect(save).toBeEnabled()
    expect(save).not.toHaveAttribute('aria-describedby')
    expect(screen.queryByText('Uzupełnij: Okno kontekstu (tokeny)')).not.toBeInTheDocument()
  })

  it('błąd API: Alert w dialogu z przyczyną, pola zostają', async () => {
    server.use(failingPatch())
    await renderDialog({ model: model() })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Równoległe zapytania'), '24')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(
      await screen.findByText('Nie udało się wykonać operacji: E2E: symulowana awaria zapisu'),
    ).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Okno kontekstu (tokeny)')).toHaveValue(4096)
    expect(screen.getByLabelText('Równoległe zapytania')).toHaveValue(24)
  })

  it('Anuluj wywołuje onClose', async () => {
    const { onClose } = await renderDialog({ model: model() })

    await userEvent.setup().click(screen.getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})

describe('formFromModel', () => {
  it('brak klucza max_concurrency → puste pole', () => {
    expect(formFromModel(model({ extra: {} }))).toEqual({ maxTokens: '4096', concurrency: '' })
  })

  it('max_tokens null → domyślne 8192 (T7 D1: zasiew tworzy modele bez okna kontekstu)', () => {
    expect(formFromModel(model({ max_tokens: null, extra: { max_concurrency: 24 } }))).toEqual({
      maxTokens: '8192',
      concurrency: '24',
    })
  })
})

describe('EditModelDialog — T7 D1: model z max_tokens null', () => {
  it('otwiera się bez błędu, 24 aktywuje Zapisz, PATCH ma 8192 i max_concurrency 24', async () => {
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDialog({
      model: model({ max_tokens: null, extra: {} }),
    })
    const user = userEvent.setup()

    // Dialog otwarty bez błędu walidacji, „Zapisz” aktywny od razu.
    expect(screen.getByLabelText('Okno kontekstu (tokeny)')).toHaveValue(8192)
    expect(screen.queryByText('Co najmniej 1024')).toBeNull()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

    await user.type(screen.getByLabelText('Równoległe zapytania'), '24')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ max_tokens: 8192, extra: { max_concurrency: 24 } })
  })
})
