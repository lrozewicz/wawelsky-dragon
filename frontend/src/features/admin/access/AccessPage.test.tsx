/**
 * Dostęp do asystentów (brief T5, kontrakt WP E3-6c2 §4): przykłady wejście → wyjście z briefu —
 * wybór e-maila, lista czatów z grantami (automatyczny zaznaczony i zablokowany), zapis zbioru.
 */

import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  adminHandlers,
  apiUrl,
  chatListItem,
  chatsHandlers,
  makeGrant,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { AccessPage } from './AccessPage'

afterEach(cleanup)

const JAN = 'jan@wd.test'

/** Trzy czaty z briefu — c1, c2, c3. */
function chatFixtures() {
  return chatsHandlers([
    chatListItem({ id: 'c1', name: 'Czat pierwszy' }),
    chatListItem({ id: 'c2', name: 'Czat drugi' }),
    chatListItem({ id: 'c3', name: 'Czat trzeci' }),
  ])
}

/** Granty z briefu: c1 automatyczny (neutralny marker z sufiksem, DEC-312), c3 ręczny. */
function grantSeed() {
  return adminHandlers({
    grants: {
      [JAN]: [makeGrant('c1', 'hub-compat-auto-provisioning'), makeGrant('c3', 'admin@wd.test')],
    },
  })
}

/** Wybór e-maila: wpisanie wartości i zatwierdzenie Enterem (Autocomplete `freeSolo`). */
function pickEmail(value: string): void {
  const input = screen.getByTestId('admin-access-email')
  fireEvent.change(input, { target: { value } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

function checkbox(chatId: string): HTMLInputElement {
  return screen.getByTestId(`admin-access-chat-${chatId}`) as HTMLInputElement
}

describe('AccessPage', () => {
  it('bez e-maila pokazuje zachętę do wyboru użytkownika', async () => {
    server.use(...grantSeed(), ...chatFixtures())

    await renderWithProviders(<AccessPage />)

    expect(await screen.findByTestId('admin-access')).toBeInTheDocument()
    expect(screen.getByText('Wybierz użytkownika, aby zobaczyć jego dostęp.')).toBeInTheDocument()
  })

  it('grant automatyczny jest zaznaczony i zablokowany z chipem, grant ręczny zaznaczony', async () => {
    server.use(...grantSeed(), ...chatFixtures())

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)

    await waitFor(() => expect(checkbox('c1')).toBeChecked())
    expect(checkbox('c1')).toBeDisabled()
    expect(checkbox('c3')).toBeChecked()
    expect(checkbox('c2')).not.toBeChecked()
    expect(screen.getByText('Nadany automatycznie')).toBeInTheDocument()
    expect(
      screen.getByText('Dostęp nadany automatycznie nie może być odebrany tutaj.'),
    ).toBeInTheDocument()
  })

  it('zapis wysyła zbiór wraz z grantem automatycznym i pokazuje potwierdzenie', async () => {
    const bodies: { email: string; chat_ids: string[] }[] = []
    server.use(
      // Nadpisanie na początku listy MSW wygrywa z handlerem z `adminHandlers`.
      http.put(apiUrl('/api/wd/v1/access/assistants'), async ({ request }) => {
        bodies.push((await request.json()) as { email: string; chat_ids: string[] })
        return HttpResponse.json({ data: { email: JAN, count: 3 } })
      }),
      ...grantSeed(),
      ...chatFixtures(),
    )

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)
    await waitFor(() => expect(checkbox('c3')).toBeChecked())

    fireEvent.click(checkbox('c2'))
    fireEvent.click(screen.getByTestId('admin-access-save'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]?.email).toBe(JAN)
    expect([...(bodies[0]?.chat_ids ?? [])].sort()).toEqual(['c1', 'c2', 'c3'])
    expect(await screen.findByText('Dostęp zapisany.')).toBeInTheDocument()
  })

  it('odznaczenie grantu usuwa go z listy po kolejnym pobraniu grantów', async () => {
    server.use(...grantSeed(), ...chatFixtures())

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)
    await waitFor(() => expect(checkbox('c3')).toBeChecked())

    fireEvent.click(checkbox('c3'))
    fireEvent.click(screen.getByTestId('admin-access-save'))
    await screen.findByText('Dostęp zapisany.')

    const response = await fetch(
      `${apiUrl('/api/wd/v1/access/assistants')}?email=${encodeURIComponent(JAN)}`,
    )
    const payload = (await response.json()) as { data: { items: { chat_id: string }[] } }
    expect(payload.data.items.map((grant) => grant.chat_id)).toEqual(['c1'])
    expect(checkbox('c3')).not.toBeChecked()
    expect(checkbox('c1')).toBeChecked()
  })

  it('błąd zapisu pokazuje Alert z komunikatem dla sluga błędu', async () => {
    server.use(
      http.put(apiUrl('/api/wd/v1/access/assistants'), () =>
        HttpResponse.json(
          { error: { code: 'validation_failed', message: 'invalid' } },
          { status: 400 },
        ),
      ),
      ...grantSeed(),
      ...chatFixtures(),
    )

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)
    await waitFor(() => expect(checkbox('c3')).toBeChecked())

    fireEvent.click(checkbox('c2'))
    fireEvent.click(screen.getByTestId('admin-access-save'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Dane są niepoprawne.')
  })

  it('brak czatów pokazuje komunikat zamiast listy', async () => {
    server.use(...adminHandlers(), ...chatsHandlers([]))

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)

    expect(await screen.findByText('Brak czatów do udostępnienia.')).toBeInTheDocument()
  })

  it('zapis jest wyłączony bez zmian i włącza się po zmianie zbioru', async () => {
    server.use(...grantSeed(), ...chatFixtures())

    await renderWithProviders(<AccessPage />)
    await screen.findByTestId('admin-access')
    pickEmail(JAN)
    await waitFor(() => expect(checkbox('c3')).toBeChecked())

    const save = screen.getByTestId('admin-access-save')
    expect(save).toBeDisabled()

    fireEvent.click(checkbox('c2'))
    expect(save).toBeEnabled()

    fireEvent.click(checkbox('c2'))
    expect(save).toBeDisabled()
  })
})
