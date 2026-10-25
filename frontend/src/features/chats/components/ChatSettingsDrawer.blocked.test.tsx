/**
 * Poprawki QA-UI szuflady ustawień czatu (T10): widoczny powód blokady „Zapisz” (D1) i toast
 * zapisu z `autoHideDuration` (D4). Osobny plik, bo `ChatSettingsDrawer.test.tsx` ma na HEAD
 * dokładnie 300 linii — limit `max-lines` z `eslint.config.js` (DEC-098).
 */

import type { ReactNode } from 'react'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ShowNotificationOptions } from '../../../hooks/useNotifications/useNotifications'
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

// Podsłuch powiadomień: wywołanie `show` ląduje w `showSpy`, a wyświetlanie zostaje prawdziwemu
// providerowi — toast nadal trafia do DOM, więc asercja widoczności niżej nie kłamie.
const { showSpy } = vi.hoisted(() => ({ showSpy: vi.fn() }))

vi.mock('../../../hooks/useNotifications/useNotifications', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../hooks/useNotifications/useNotifications')>()
  return {
    ...actual,
    default: () => {
      const notifications = actual.default()
      return {
        ...notifications,
        show: (message: ReactNode, options?: ShowNotificationOptions) => {
          showSpy(message, options)
          return notifications.show(message, options)
        },
      }
    },
  }
})

afterEach(cleanup)

beforeEach(() => {
  showSpy.mockClear()
})

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

describe('ChatSettingsDrawer (blokada zapisu i toast)', () => {
  it('wybór bazy bez {knowledge} pokazuje powód blokady i przenosi na zakładkę promptu', async () => {
    useChat({ dataset_ids: ['ds-1'] })
    await renderDrawer()
    const user = userEvent.setup()

    // Pole z błędem leży na „Silniku promptu”, a szuflada otwiera się na „Asystencie”.
    const hint = screen.getByRole('alert')
    expect(hint).toHaveTextContent('Silnik promptu')
    expect(hint).toHaveTextContent(
      'Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.',
    )
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()

    await user.click(within(hint).getByRole('button', { name: 'Przejdź' }))

    expect(screen.getByRole('tab', { name: 'Silnik promptu' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByLabelText(/Prompt systemowy/)).toBeInTheDocument()
    // Na zakładce z błędnym polem alert nie dubluje komunikatu — zostaje sam helper text przy polu.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(
      screen.getAllByText('Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.'),
    ).toHaveLength(1)

    fireEvent.change(screen.getByLabelText(/Prompt systemowy/), {
      target: { value: 'Odpowiadaj z {knowledge}.' },
    })

    await waitFor(() =>
      expect(
        screen.queryByText('Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.'),
      ).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
  })

  it('U11: klik „Zapisz” przy błędzie przenosi na zakładkę promptu z fokusem w polu', async () => {
    useChat({ dataset_ids: ['ds-1'] })
    await renderDrawer()
    const user = userEvent.setup()

    // Błąd leży na „Silniku promptu”, szuflada otwiera się na „Asystencie”. Najpierw zmiana
    // opisu: bez zmian „Zapisz” wyłącza brak zmian — nie błąd (U11).
    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Inny opis' } })
    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeEnabled()

    await user.click(save)

    expect(screen.getByRole('tab', { name: 'Silnik promptu' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByLabelText(/Prompt systemowy/)).toHaveFocus()
    // PUT nie wychodzi — komunikat błędu zostaje przy polu.
    expect(
      screen.getAllByText('Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.'),
    ).toHaveLength(1)
  })

  it('U11 (T9): po kliku „Zapisz” ręczna zmiana zakładki nie przeskakuje fokusem do pola', async () => {
    useChat({ dataset_ids: ['ds-1'] })
    await renderDrawer()
    const user = userEvent.setup()

    // Klik „Zapisz” przy błędzie: przenosi na „Silnik promptu” i focusuje pole promptu.
    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Jeszcze inny opis' } })
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))
    expect(screen.getByLabelText(/Prompt systemowy/)).toHaveFocus()

    // Ręczny powrót na „Asystenta”: żądanie fokusu zostało już skonsumowane, więc fokus
    // zostaje na zakładce — nie cofa się do pola „Nazwa” (stare [focusTick, tab] cofało
    // fokus przy każdej ręcznej zmianie zakładki).
    await user.click(screen.getByRole('tab', { name: 'Asystent' }))

    expect(screen.getByRole('tab', { name: 'Asystent' })).toHaveFocus()
  })

  it('toast zapisu znika sam — show z autoHideDuration 4000', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Nowy opis' } })
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    await waitFor(() =>
      expect(showSpy).toHaveBeenCalledWith('Zapisano ustawienia czatu.', {
        severity: 'success',
        autoHideDuration: 4000,
      }),
    )
  })
})
