/**
 * Dialog „Dodaj model” (brief E3-6c1 T6 pkt 3): ciało `POST …/models` z domyślnym `max_tokens`,
 * polem wymiaru tylko dla embeddingu i `Alert` przy błędzie 101/102.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { AddModelDialog } from './AddModelDialog'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
})

const MODELS_URL = apiUrl('/api/v1/providers/litellm/instances/inst-1/models')

/** Przechwytuje ciała `POST …/models` i zwraca sukces bez `data`. */
function capturePost(bodies: unknown[]) {
  return http.post(MODELS_URL, async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({ code: 0, message: 'success' })
  })
}

/** Otwiera select po `data-testid` i klika opcję po nazwie. */
async function chooseType(option: string): Promise<void> {
  const user = userEvent.setup()
  const field = screen.getByTestId('add-model-type')
  await user.click(within(field).getByRole('combobox'))
  await user.click(await screen.findByRole('option', { name: option }))
}

async function renderDialog(onClose = vi.fn()) {
  const result = await renderWithProviders(
    <AddModelDialog instanceId="inst-1" open onClose={onClose} />,
  )
  return { ...result, onClose }
}

describe('AddModelDialog', () => {
  it('wysyła embedding z domyślnym max_tokens i wymiarem', async () => {
    const bodies: unknown[] = []
    server.use(capturePost(bodies))
    const { onClose } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa modelu/), 'm1')
    await chooseType('Embedding')
    await user.type(screen.getByLabelText('Wymiar'), '768')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      model_name: 'm1',
      model_type: 'embedding',
      max_tokens: 8192,
      wd_dimension: 768,
    })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('pokazuje pole wymiaru tylko dla typu embedding', async () => {
    await renderDialog()

    expect(screen.queryByLabelText('Wymiar')).toBeNull()
    await chooseType('Embedding')
    expect(await screen.findByLabelText('Wymiar')).toBeInTheDocument()
  })

  it('blokuje zapis, dopóki nazwa jest pusta', async () => {
    await renderDialog()

    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
    await userEvent.setup().type(screen.getByLabelText(/Nazwa modelu/), 'm1')
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
  })

  it('SC-V12-08: nieaktywny „Zapisz” ma powód z aria-describedby, który znika po poprawie', async () => {
    await renderDialog()
    const user = userEvent.setup()
    const save = screen.getByRole('button', { name: 'Zapisz' })

    // Pusta wymagana nazwa → powód pod przyciskiem, powiązany aria-describedby.
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'add-model-save-reason')
    expect(screen.getByText('Uzupełnij: Nazwa modelu')).toHaveAttribute(
      'id',
      'add-model-save-reason',
    )

    // Nazwa ok, ale okno kontekstu poza zakresem → powód mówi, co poprawić.
    await user.type(screen.getByLabelText(/Nazwa modelu/), 'm1')
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '100')
    expect(save).toBeDisabled()
    expect(screen.getByText('Popraw: Okno kontekstu (tokeny)')).toBeInTheDocument()

    // Poprawa → powód i atrybut znikają, przycisk aktywny.
    await user.clear(screen.getByLabelText('Okno kontekstu (tokeny)'))
    await user.type(screen.getByLabelText('Okno kontekstu (tokeny)'), '4096')
    expect(save).toBeEnabled()
    expect(save).not.toHaveAttribute('aria-describedby')
    expect(screen.queryByText('Popraw: Okno kontekstu (tokeny)')).not.toBeInTheDocument()
  })

  it('pokazuje błąd 102 jako `Alert` i zostawia dialog otwarty', async () => {
    server.use(
      http.post(MODELS_URL, () =>
        HttpResponse.json({ code: 102, message: "Model 'm1' already exists" }),
      ),
    )
    await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(/Nazwa modelu/), 'm1')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(
      await screen.findByText("Nie udało się wykonać operacji: Model 'm1' already exists"),
    ).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
