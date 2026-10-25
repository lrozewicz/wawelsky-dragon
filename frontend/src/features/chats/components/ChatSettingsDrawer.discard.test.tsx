/**
 * Strażnik niezapisanych zmian szuflady ustawień czatu (SC-V12-07): „Anuluj” przy zmianach pyta
 * „Odrzucić zmiany?”, a „Odrzuć” zamyka szufladę bez wysłania zapisu; bez zmian „Anuluj” zamyka
 * od razu, bez dialogu. Osobny plik (wzorzec: `SearchSettingsDrawer.discard.test.tsx`) — główny
 * plik testów szuflady trzyma limit 300 linii.
 */

import { cleanup, fireEvent, screen } from '@testing-library/react'
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
import { server } from '../../../test/msw/server'

import { ChatSettingsDrawer } from './ChatSettingsDrawer'

afterEach(cleanup)

/** Czat w stanie MSW (widoczny dla GET /chats/:id) + trzy bazy wiedzy z `fixtureChatDatasets`. */
function useChat(): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: 'chat-1', name: 'Alfa' })]),
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

/** PATCH czatu ze sukcesem i zapisem ciała żądania — sprawdzenie, że „Odrzuć” nic nie wysyła. */
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

describe('ChatSettingsDrawer — niezapisane zmiany (SC-V12-07)', () => {
  it('„Anuluj” przy zmianach pyta „Odrzucić zmiany?”; „Odrzuć” zamyka bez zapisu', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const { onClose } = await renderDrawer()
    const user = userEvent.setup()

    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Nowy opis' } })
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(await screen.findByText('Odrzucić zmiany?')).toBeInTheDocument()
    expect(
      screen.getByText('Niezapisane zmiany w ustawieniach czatu zostaną utracone.'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Odrzuć' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(bodies).toEqual([])
  })

  it('„Anuluj” bez zmian zamyka szufladę od razu, bez dialogu', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const { onClose } = await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Odrzucić zmiany?')).not.toBeInTheDocument()
    expect(bodies).toEqual([])
  })
})
