/**
 * Dialog tworzenia klucza API (brief E3-6c1 T4): opcjonalna nazwa, pełny token pokazywany
 * wyłącznie raz (z kopiowaniem) i czyszczenie stanu mutacji przy zamknięciu — po ponownym
 * otwarciu tokenu nie ma ani w DOM, ani w stanie mutacji.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, settingsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { CreateKeyDialog } from './CreateKeyDialog'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
  // Test porażki kopiowania usuwa `navigator.clipboard` (HTTP) — przywracamy brak własności.
  Reflect.deleteProperty(navigator, 'clipboard')
})

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Dialog trzymany w stanie rodzica — pozwala zamknąć go i otworzyć ponownie bez odmontowania. */
function Harness(): JSX.Element {
  const [open, setOpen] = useState(true)

  return (
    <>
      <button onClick={() => setOpen(true)}>reopen</button>
      <CreateKeyDialog open={open} onClose={() => setOpen(false)} />
    </>
  )
}

describe('CreateKeyDialog', () => {
  it('tworzy klucz z przyciętą nazwą i pokazuje pełny token raz', async () => {
    const user = userEvent.setup()
    const calls = recordRequests()
    server.use(...settingsHandlers({ tokens: [] }))

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Nowy klucz API')).toBeInTheDocument()

    await user.type(within(dialog).getByRole('textbox', { name: 'Nazwa (opcjonalna)' }), ' ci ')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    const token = (await screen.findByTestId('settings-new-token')).textContent ?? ''
    expect(token.startsWith('ragflow-')).toBe(true)
    expect(calls).toContain('POST /api/v1/system/tokens?name=ci')
    expect(screen.getByText('Skopiuj teraz — nie zobaczysz go ponownie')).toBeInTheDocument()
  })

  it('pole nazwy ma limit 128 znaków i licznik (V12-3 T2)', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog')
    const nameField = within(dialog).getByRole('textbox', { name: 'Nazwa (opcjonalna)' })
    expect(nameField).toHaveAttribute('maxLength', '128')
    expect(within(dialog).getByText('0/128')).toBeInTheDocument()

    await user.type(nameField, 'abc')
    expect(within(dialog).getByText('3/128')).toBeInTheDocument()
  })

  it('dwa szybkie kliknięcia „Utwórz” to jedno żądanie i koniec widoku tworzenia (U2)', async () => {
    // `pointerEventsCheck: 0` — drugie kliknięcie celowo trafia w zablokowany przycisk
    // (MUI ustawia wtedy `pointer-events: none`); sprawdzamy, że i tak nie ma drugiego żądania.
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const calls = recordRequests()
    // Spowolniona odpowiedź: drugie kliknięcie wpada, zanim mutacja się skończy.
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), async () => {
        await delay(50)
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { token: 'ragflow-two01234567890123456789012345', create_date: '2025-06-01' },
        })
      }),
    )

    // `Harness` trzyma stan otwarcia, więc „Zamknij” naprawdę zamyka dialog.
    await renderWithProviders(<Harness />)
    const dialog = screen.getByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Utwórz' })

    await user.click(submit)
    // Przycisk jest zablokowany w trakcie żądania…
    expect(submit).toBeDisabled()
    // …więc drugie kliknięcie nie wysyła kolejnego żądania.
    await user.click(submit)

    await screen.findByTestId('settings-new-token')
    expect(calls.filter((call) => call.startsWith('POST ')).length).toBe(1)
    // Po sukcesie widok tworzenia jest zamknięty: bez pola nazwy i bez przycisku „Utwórz”.
    expect(within(dialog).queryByRole('textbox', { name: 'Nazwa (opcjonalna)' })).toBeNull()
    expect(within(dialog).queryByRole('button', { name: 'Utwórz' })).toBeNull()

    await user.click(within(dialog).getByRole('button', { name: 'Zamknij' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('dwa kliknięcia „Utwórz” w tej samej klatce to jedno żądanie (U2, dblclick)', async () => {
    const calls = recordRequests()
    // Spowolniona odpowiedź: żądania zdążą się policzyć, zanim mutacja się skończy.
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), async () => {
        await delay(50)
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { token: 'ragflow-dbl01234567890123456789012345', create_date: '2025-06-01' },
        })
      }),
    )

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Utwórz' })

    // Dwa kliknięcia w tej samej klatce, bez przerwy na przelanie stanu Reacta — tak zachowuje
    // się dblclick. Strażnik `isPending` z hooka jest wtedy jeszcze nieodświeżony (U2), więc
    // duplikat żądania musi łapać strażnik synchroniczny.
    act(() => {
      fireEvent.click(submit)
      fireEvent.click(submit)
    })

    await screen.findByTestId('settings-new-token')
    expect(calls.filter((call) => call.startsWith('POST ')).length).toBe(1)
  })

  it('po błędzie tworzenia kolejne kliknięcie „Utwórz” ponawia żądanie', async () => {
    let attempts = 0
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), () => {
        attempts += 1
        if (attempts === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { token: 'ragflow-retry01234567890123456789012', create_date: '2025-06-01' },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    await screen.findByText('Nie udało się wykonać operacji: boom')

    // Strażnik synchroniczny musi zostać zwolniony po błędzie, inaczej ponowienie nie zadziała.
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    const token = await screen.findByTestId('settings-new-token')
    expect(token.textContent).toBe('ragflow-retry01234567890123456789012')
  })

  it('wysyła POST bez parametru `name`, gdy pole nazwy jest puste', async () => {
    const user = userEvent.setup()
    const calls = recordRequests()
    server.use(...settingsHandlers({ tokens: [] }))

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    await screen.findByTestId('settings-new-token')

    expect(calls).toContain('POST /api/v1/system/tokens')
  })

  it('kopiuje utworzony token do schowka', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    const token = (await screen.findByTestId('settings-new-token')).textContent ?? ''

    await user.click(screen.getByRole('button', { name: 'Kopiuj token' }))

    await expect(navigator.clipboard.readText()).resolves.toBe(token)
  })

  it('porażka kopiowania tokenu pokazuje błąd i zaznacza token do ręcznej kopii', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))
    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    const token = (await screen.findByTestId('settings-new-token')).textContent ?? ''

    // Stos HTTP: `navigator.clipboard` nie istnieje, a jsdom nie ma `execCommand` —
    // kopiowanie się nie udaje (defekt MAJOR z QA-UI E6-2-2: wtedy dialog pokazywał
    // „Skopiowano”, choć schowek był bez zmian).
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Kopiuj token' }))

    expect(screen.getByTestId('settings-copy-error')).toHaveTextContent('Nie udało się skopiować')
    expect(screen.queryByRole('button', { name: 'Skopiowano' })).toBeNull()
    // Token zaznaczony w dokumencie — użytkownik może go skopiować ręcznie (Ctrl+C).
    expect(document.getSelection()?.toString()).toBe(token)
  })

  it('po zamknięciu i ponownym otwarciu nie pokazuje tokenu', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))
    await renderWithProviders(<Harness />)

    await user.click(screen.getByRole('button', { name: 'Utwórz' }))
    await screen.findByTestId('settings-new-token')

    await user.click(screen.getByRole('button', { name: 'Zamknij' }))
    // Przycisk poza modalem: `getByText`, bo otwarty `Dialog` ukrywa resztę drzewa przed ARIA.
    await user.click(screen.getByText('reopen'))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByTestId('settings-new-token')).not.toBeInTheDocument()
  })

  it('pokazuje błąd mutacji z nagłówkiem i komunikatem z API', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), () =>
        HttpResponse.json({ code: 101, message: 'name is too long' }),
      ),
    )

    await renderWithProviders(<CreateKeyDialog open onClose={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Utwórz' }))

    expect(
      await screen.findByText('Nie udało się wykonać operacji: name is too long'),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('settings-new-token')).not.toBeInTheDocument())
  })

  it('zamyka dialog po kliknięciu Zamknij', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))

    await renderWithProviders(<CreateKeyDialog open onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Zamknij' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
