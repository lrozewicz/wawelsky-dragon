/**
 * Strażnik defektu QA E6-1b-2 (SC-05 k2, MAJOR) — osobny plik, bo `ChatSettingsDrawer.test.tsx`
 * jest na limicie linii eslint. Scenariusz: przełącznik „Pokaż cytowania” (`prompt_config.quote`)
 * po zmianie ma aktywować „Zapisz”, a PATCH ma nieść quote; backend przy tworzeniu sieje
 * quote=true (chat_validation), więc po odczycie przełącznik jest włączony.
 */
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  apiUrl,
  chatDetail,
  chatListItem,
  chatsHandlers,
  datasetsHandlers,
  fixtureChatDatasets,
} from '../../../test/msw/handlers'
import type { FixtureChatListItem } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { ChatSettingsDrawer } from './ChatSettingsDrawer'

afterEach(cleanup)

/** Czat w stanie MSW (widoczny dla GET /chats/:id) + baza wiedzy z `fixtureChatDatasets`. */
function useChat(overrides: Partial<FixtureChatListItem> = {}): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: 'chat-1', name: 'Alfa', ...overrides })]),
    ...datasetsHandlers(fixtureChatDatasets),
  )
}

/** PATCH czatu ze sukcesem i zapisem ciała żądania — sprawdzenie, co realnie wysyła szuflada. */
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

describe('ChatSettingsDrawer — przełącznik „Pokaż cytowania” (QA E6-1b-2 B)', () => {
  it('aktywuje „Zapisz” i zapisuje quote w prompt_config', async () => {
    // Jak w QA SC-05: asystent utworzony z bazą (backend sieje system z {knowledge}).
    useChat({
      dataset_ids: ['ds-1'],
      prompt_config: { system: 'Odpowiadaj z {knowledge}.' },
    })
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderWithProviders(<ChatSettingsDrawer chatId="chat-1" open onClose={vi.fn()} />)
    await screen.findByRole('tab', { name: 'Asystent' })
    const user = userEvent.setup()

    const quoteSwitch = screen.getByRole('switch', { name: 'Pokazuj cytowania' })
    // Domyślny backendu (chat_validation: quote=True) — przy tworzeniu włączony.
    expect(quoteSwitch).toBeChecked()

    await user.click(quoteSwitch)
    // Zgłoszenie QA: po zmianie samego przełącznika „Zapisz” pozostawał nieaktywny.
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    await waitFor(() => expect(bodies).toHaveLength(1))
    const patch = bodies[0] as { prompt_config?: { quote?: boolean } }
    expect(patch.prompt_config?.quote).toBe(false)
  })
})
