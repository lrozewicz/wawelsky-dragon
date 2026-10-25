import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  apiUrl,
  datasetsHandlers,
  fixtureChatDatasets,
  fixtureModel,
  modelsHandlers,
  resetSearchesFixtures,
  searchFixtureApp,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import type { SearchApp } from '../queries'

import { SearchSettingsDrawer } from './SearchSettingsDrawer'

afterEach(cleanup)
// Magazyn MSW jest wspólny dla pliku — każdy test startuje od ziarna `searchFixtureApp`.
beforeEach(resetSearchesFixtures)

/** Ciało `PUT /searches/{id}` — pełne pola wyszukiwarki i scalony `search_config`. */
type PutBody = { name: string; description: string; search_config: Record<string, unknown> }

/** Rejestr modeli: model czatu i model rerank (do comboboxów „Model podsumowania” i „Model rerank”). */
const MODEL_FIXTURES = [
  fixtureModel({ model_id: 'id-chat-1', name: 'fake-chat' }),
  fixtureModel({ model_id: 'id-rerank', name: 'fake-rerank', model_type: ['rerank'] }),
]

/** Bazy wiedzy i rejestr modeli podmieniane w każdym teście szuflady. */
function useFixtures(): void {
  server.use(...datasetsHandlers(fixtureChatDatasets), ...modelsHandlers(MODEL_FIXTURES))
}

/** PUT przechwytujący ciało żądania — sprawdzenie, co realnie wysyła szuflada. */
function capturePut(bodies: unknown[]) {
  return http.put(apiUrl('/api/v1/searches/:searchId'), async ({ request, params }) => {
    bodies.push(await request.json())
    return HttpResponse.json({
      code: 0,
      message: '',
      data: { ...searchFixtureApp, id: String(params.searchId) },
    })
  })
}

/** Wyszukiwarka z podmienionym fragmentem `search_config`. */
function appWith(config: Record<string, unknown>): SearchApp {
  return { ...searchFixtureApp, search_config: { ...searchFixtureApp.search_config, ...config } }
}

async function renderDrawer(app: SearchApp, onClose: () => void = vi.fn()) {
  const result = await renderWithProviders(
    <SearchSettingsDrawer app={app} open onClose={onClose} />,
  )
  await screen.findByLabelText(/Nazwa wyszukiwarki/)
  return { ...result, onClose }
}

/** Opcja listy rozwijanej po widocznym tekście (nazwy MUI liczy inaczej). */
async function optionByText(text: string): Promise<HTMLElement> {
  const options = await screen.findAllByRole('option')
  const found = options.find((option) => option.textContent === text)
  if (found === undefined) throw new Error(`Brak opcji listy: ${text}`)
  return found
}

describe('SearchSettingsDrawer', () => {
  it('pokazuje pola z wartościami z search_config', async () => {
    useFixtures()
    await renderDrawer(searchFixtureApp)

    expect(screen.getByLabelText(/Nazwa wyszukiwarki/)).toHaveValue('Wyszukiwarka testowa')
    expect(screen.getByLabelText('Opis')).toHaveValue('Wyszukiwarka demonstracyjna')
    expect(screen.getByLabelText(/Bazy wiedzy/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Podsumowanie AI' })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Model podsumowania' })).toHaveValue('fake-chat')
    expect(screen.getByRole('switch', { name: 'Pytania pokrewne' })).toBeChecked()
  })

  it('brak baz wiedzy blokuje zapis i pokazuje błąd kbIdsRequired', async () => {
    useFixtures()
    await renderDrawer(appWith({ kb_ids: [] }))

    // SC-V12-08: Zapisz nieaktywny — klik nie jest potrzebny, błąd pola widać od razu.
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
    expect(screen.getByText('Wybierz co najmniej jedną bazę wiedzy.')).toBeInTheDocument()
  })

  it('SC-V12-08: brak baz — Zapisz nieaktywny z powodem „Popraw: Bazy wiedzy” i aria-describedby', async () => {
    useFixtures()
    await renderDrawer(appWith({ kb_ids: [] }))
    const user = userEvent.setup()

    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'search-settings-save-reason')
    // Powód pod przyciskiem mówi, CO poprawić; błąd pola zostaje przy polu.
    expect(screen.getByText('Popraw: Bazy wiedzy')).toBeInTheDocument()
    expect(screen.getByText('Wybierz co najmniej jedną bazę wiedzy.')).toBeInTheDocument()

    // Wybór bazy: formularz poprawny → przycisk aktywny, powód i atrybut znikają.
    await user.click(screen.getByLabelText(/Bazy wiedzy/))
    await user.click(await optionByText('Baza wiedzy'))
    expect(save).toBeEnabled()
    expect(save.getAttribute('aria-describedby'), 'atrybut powodu zdjęty').toBeNull()
    expect(screen.queryByText('Popraw: Bazy wiedzy')).not.toBeInTheDocument()
  })

  it('SC-V12-08: pusta nazwa — powód „Uzupełnij: Nazwa wyszukiwarki”', async () => {
    useFixtures()
    // `name` leży w korzeniu `SearchApp` (nie w `search_config`), więc bez `appWith`.
    await renderDrawer({ ...searchFixtureApp, name: '   ' })

    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'search-settings-save-reason')
    expect(screen.getByText('Uzupełnij: Nazwa wyszukiwarki')).toBeInTheDocument()
  })

  it('podsumowanie bez modelu blokuje zapis i pokazuje błąd llmRequired', async () => {
    useFixtures()
    await renderDrawer(appWith({ summary: true, chat_id: '' }))

    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
    expect(screen.getByText('Wybierz model podsumowania.')).toBeInTheDocument()
  })

  it('SC-V13-11: bez zmian „Zapisz” nieaktywny z powodem „Brak zmian do zapisania”; zmiana aktywuje', async () => {
    useFixtures()
    await renderDrawer(searchFixtureApp)

    // K1: formularz poprawny, ale bez zmian — wspólny powód pod przyciskiem (aria-describedby).
    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'search-settings-save-reason')
    expect(screen.getByText('Brak zmian do zapisania')).toBeInTheDocument()

    // K2: zmiana pola gasi powód i aktywuje przycisk.
    const user = userEvent.setup()
    const opis = screen.getByLabelText('Opis') as HTMLTextAreaElement
    const original = opis.value
    await user.type(opis, ' zmiana')
    expect(save).toBeEnabled()
    expect(save.getAttribute('aria-describedby'), 'atrybut powodu zdjęty').toBeNull()
    expect(screen.queryByText('Brak zmian do zapisania')).not.toBeInTheDocument()

    // K3: cofnięcie do wartości pierwotnej przywraca stan wyjściowy.
    await user.clear(opis)
    await user.type(opis, original)
    expect(save).toBeDisabled()
    expect(screen.getByText('Brak zmian do zapisania')).toBeInTheDocument()
  })

  it('zapis wysyła pełne ciało i zachowuje klucz use_kg', async () => {
    useFixtures()
    const bodies: unknown[] = []
    server.use(capturePut(bodies))
    const { onClose } = await renderDrawer(searchFixtureApp)
    const user = userEvent.setup()

    // Bez zmian „Zapisz” jest nieaktywny (SC-V13-11) — zmiana opisu otwiera zapis.
    await user.type(screen.getByLabelText('Opis'), ' poprawiona')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    const body = bodies[0] as PutBody
    expect(body.name).toBe('Wyszukiwarka testowa')
    expect(body.description).toBe('Wyszukiwarka demonstracyjna poprawiona')
    expect(body.search_config.use_kg).toBe(false)
    expect(body.search_config.kb_ids).toEqual(['ds-1'])
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Zapisano ustawienia wyszukiwarki.')).toBeInTheDocument()
  })

  it('wybór modelu rerank zapisuje jego nazwę w rerank_id', async () => {
    useFixtures()
    const bodies: unknown[] = []
    server.use(capturePut(bodies))
    await renderDrawer(searchFixtureApp)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    await user.click(screen.getByRole('switch', { name: 'Użyj modelu rerank' }))
    await user.click(screen.getByRole('combobox', { name: 'Model rerank' }))
    await user.click(await optionByText('fake-rerank'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect((bodies[0] as PutBody).search_config.rerank_id).toBe('fake-rerank')
  })

  it('pole modelu i preset są widoczne tylko przy włączonym podsumowaniu', async () => {
    useFixtures()
    await renderDrawer(searchFixtureApp)
    const user = userEvent.setup()

    expect(screen.getByRole('combobox', { name: 'Model podsumowania' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    expect(screen.getByRole('combobox', { name: 'Kreatywność' })).toBeInTheDocument()

    await user.click(screen.getByRole('switch', { name: 'Podsumowanie AI' }))

    expect(screen.queryByRole('combobox', { name: 'Model podsumowania' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Kreatywność' })).not.toBeInTheDocument()
  })

  it('błąd API pokazuje Alert i nie zamyka szuflady', async () => {
    useFixtures()
    server.use(
      http.put(apiUrl('/api/v1/searches/:searchId'), () =>
        HttpResponse.json({ code: 102, message: 'Brak uprawnień', data: null }),
      ),
    )
    const { onClose } = await renderDrawer(searchFixtureApp)
    const user = userEvent.setup()

    // Bez zmian „Zapisz” jest nieaktywny (SC-V13-11) — zmiana opisu otwiera zapis.
    await user.type(screen.getByLabelText('Opis'), ' poprawiona')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Brak uprawnień')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('przycisk zamknięcia ma aria-label i woła onClose', async () => {
    useFixtures()
    const { onClose } = await renderDrawer(searchFixtureApp)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zamknij ustawienia' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
