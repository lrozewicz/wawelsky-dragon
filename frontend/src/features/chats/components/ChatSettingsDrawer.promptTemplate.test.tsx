/**
 * Szablon promptu z `{knowledge}` przy wyborze bazy (kontrakt WP E5-H6e C2): pierwsza baza wiedzy
 * przy pustym prompcie systemowym wypełnia pole „Prompt systemowy” tekstem `DEFAULT_SYSTEM_PROMPT`,
 * a niepusty prompt zostaje bez zmian. Osobny plik, bo `ChatSettingsDrawer.test.tsx` ma na HEAD
 * 300 linii — limit `max-lines` z `eslint.config.js` (wzór: `ChatSettingsDrawer.blocked.test.tsx`).
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  chatListItem,
  chatsHandlers,
  datasetsHandlers,
  fixtureChatDatasets,
} from '../../../test/msw/handlers'
import type { FixtureChatListItem } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { DEFAULT_SYSTEM_PROMPT } from '../settings/defaultPrompt'

import { ChatSettingsDrawer } from './ChatSettingsDrawer'

afterEach(cleanup)

/** Czat w stanie MSW (widoczny dla GET /chats/:id) + bazy wiedzy z `fixtureChatDatasets`. */
function useChat(overrides: Partial<FixtureChatListItem> = {}): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: 'chat-1', name: 'Alfa', ...overrides })]),
    ...datasetsHandlers(fixtureChatDatasets),
  )
}

async function renderDrawer(onClose: () => void = vi.fn()) {
  const result = await renderWithProviders(
    <ChatSettingsDrawer chatId="chat-1" open onClose={onClose} />,
  )
  await screen.findByRole('tab', { name: 'Asystent' })
  return { ...result, onClose }
}

/** Opcja listy rozwijanej po jej widocznym tekście (nazwy MUI liczy inaczej). */
async function optionByText(text: string): Promise<HTMLElement> {
  const options = await screen.findAllByRole('option')
  const found = options.find((option) => option.textContent === text)
  if (found === undefined) throw new Error(`Brak opcji listy: ${text}`)
  return found
}

/** Wybiera bazę wiedzy w zakładce „Asystent” i przechodzi na „Silnik promptu”. */
async function chooseDataset(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole('combobox', { name: 'Bazy wiedzy' }))
  await user.click(await optionByText('Baza wiedzy'))
  await user.click(screen.getByRole('tab', { name: 'Silnik promptu' }))
}

describe('ChatSettingsDrawer — szablon promptu przy wyborze bazy', () => {
  it('pusty prompt + wybór bazy wypełnia pole szablonem z {knowledge}', async () => {
    useChat()
    await renderDrawer()
    const user = userEvent.setup()

    await chooseDataset(user)

    expect(screen.getByLabelText(/Prompt systemowy/)).toHaveValue(DEFAULT_SYSTEM_PROMPT)
  })

  it('niepusty prompt systemowy nie jest nadpisywany wyborem bazy', async () => {
    const custom = 'Odpowiadaj zwięźle na podstawie {knowledge}.'
    useChat({
      prompt_config: {
        system: custom,
        prologue: '',
        empty_response: '',
        quote: true,
        refine_multiturn: false,
      },
    })
    await renderDrawer()
    const user = userEvent.setup()

    await chooseDataset(user)

    expect(screen.getByLabelText(/Prompt systemowy/)).toHaveValue(custom)
  })
})
