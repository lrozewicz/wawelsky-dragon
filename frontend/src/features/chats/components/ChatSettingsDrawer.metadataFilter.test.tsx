/**
 * Filtr metadanych w szufladzie ustawień czatu (WP E6-1b, SC-E6-1b-05): sekcja w „Zaawansowanym”
 * zakładki „Asystent”, zapis `meta_data_filter` jednym PATCH-em i zachowanie wartości po
 * ponownym otwarciu. Osobny plik, bo `ChatSettingsDrawer.test.tsx` siedzi na limicie
 * `max-lines` (DEC-098).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FIXTURE_SUMMARY, useSummary } from '../../../test/metadataBuilder'
import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  apiUrl,
  chatDetail,
  chatListItem,
  chatsHandlers,
  datasetsHandlers,
  fixtureChatDatasets,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { ChatSettingsDrawer } from './ChatSettingsDrawer'

afterEach(cleanup)

/** Czat w stanie MSW + trzy bazy wiedzy z `fixtureChatDatasets` (wzór głównego pliku testowego). */
function useChat(overrides: Parameters<typeof chatListItem>[0] = {}): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: 'chat-1', name: 'Alfa', ...overrides })]),
    ...datasetsHandlers(fixtureChatDatasets),
  )
}

async function renderDrawer(): Promise<void> {
  await renderWithProviders(<ChatSettingsDrawer chatId="chat-1" open onClose={vi.fn()} />)
  await screen.findByRole('tab', { name: 'Asystent' })
}

/** PATCH czatu z zapisem ciała żądania (wzór głównego pliku testowego). */
function capturePatch(bodies: unknown[]) {
  return http.patch(apiUrl('/api/v1/chats/:chatId'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({
      code: 0,
      message: 'success',
      data: chatDetail(chatListItem({ id: 'chat-1' })),
    })
  })
}

describe('ChatSettingsDrawer — filtr metadanych (E6-1b)', () => {
  it('sekcja w „Zaawansowanym” Asystenta: przełącznik trybów, świeży czat ma Wyłączony', async () => {
    useChat({ dataset_ids: ['ds-1'] })
    useSummary(FIXTURE_SUMMARY)
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    await user.click(await screen.findByText('Filtr metadanych'))
    const modes = await screen.findByRole('radiogroup', { name: 'Tryb filtra metadanych' })

    expect(within(modes).getByRole('radio', { name: 'Wyłączony' })).toBeChecked()
    // Tryby modelu dostępne w pełnym kreatorze czatu.
    expect(within(modes).getByRole('radio', { name: 'Automatyczny' })).toBeEnabled()
    expect(within(modes).getByRole('radio', { name: 'Półautomatyczny' })).toBeEnabled()
  })

  it('warunek ręczny zapisuje meta_data_filter w PATCH i tylko go', async () => {
    // Czat z bazą i systemowym promptem z {knowledge} — inaczej walidacja blokuje zapis (U11).
    useChat({
      dataset_ids: ['ds-1'],
      prompt_config: { ...chatListItem({}).prompt_config, system: 'Odpowiedz z {knowledge}.' },
    })
    useSummary(FIXTURE_SUMMARY)
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    await user.click(await screen.findByText('Filtr metadanych'))
    await user.click(await screen.findByRole('radio', { name: 'Ręczny' }))
    // Warunek dodany automatycznie po przejściu w Ręczny (kontrakt §4).
    const row = await screen.findByRole('group', { name: 'Warunek 1' })
    await user.click(within(row).getByRole('combobox', { name: 'Klucz' }))
    await user.click(await screen.findByRole('option', { name: 'typ' }))
    await user.click(within(row).getByRole('combobox', { name: 'Wartość' }))
    await user.type(within(row).getByRole('combobox', { name: 'Wartość' }), 'raport')
    await user.keyboard('{Enter}')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      meta_data_filter: {
        method: 'manual',
        logic: 'and',
        manual: [{ key: 'typ', op: '=', value: 'raport' }],
      },
    })
  })

  it('filtrowana wartość zachowuje się po ponownym otwarciu szuflady', async () => {
    // `meta_data_filter` leży w szczególe czatu (FixtureChatDetail), nie w wierszu listy.
    server.use(
      ...chatsHandlers([
        chatDetail({
          id: 'chat-1',
          name: 'Alfa',
          dataset_ids: ['ds-1'],
          meta_data_filter: {
            method: 'manual',
            logic: 'and',
            manual: [{ key: 'typ', op: '=', value: 'raport' }],
          },
        }),
      ]),
      ...datasetsHandlers(fixtureChatDatasets),
    )
    useSummary(FIXTURE_SUMMARY)
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    await user.click(await screen.findByText('Filtr metadanych'))
    expect(await screen.findByRole('radio', { name: 'Ręczny' })).toBeChecked()
    const row = await screen.findByRole('group', { name: 'Warunek 1' })
    expect(await within(row).findByRole('combobox', { name: 'Wartość' })).toHaveValue('raport')
  })
})
