/**
 * Strona kluczy API (brief E3-6c1 T4): karta „API serwera”, lista kluczy z maską tokenu,
 * kopiowanie tokenu z wiersza, usuwanie z potwierdzeniem i tworzenie klucza z tokenem
 * pokazywanym wyłącznie raz. Dane idą przez `settingsHandlers` (kontrakt §6).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { formatDateTime } from '../../../lib/format'
import { apiUrl, makeToken, settingsHandlers } from '../../../test/msw/handlers'
import type { SettingsSeed } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { stubNarrowViewport } from '../../../test/stubNarrowViewport'

import { ApiKeysPage } from './ApiKeysPage'

afterEach(() => {
  cleanup()
  server.events.removeAllListeners()
  vi.unstubAllGlobals()
})

/** Token z przykładu briefu: maska to pierwsze 12 znaków + `…` + ostatnie 4. */
const TOKEN = 'ragflow-abcdefghijklmnopqrstuvwxyz123456'
const MASKED = 'ragflow-abcd…3456'
const CREATE_DATE = '2025-06-01T12:00:00Z'

/** Adresy żądań widziane przez MSW jako „METODA /ścieżka?query”. */
function recordRequests(): string[] {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    calls.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return calls
}

/** Rejestruje stan MSW przed renderem i oddaje wynik renderu (m.in. klienta zapytań). */
async function renderPage(seed: SettingsSeed = {}) {
  server.use(...settingsHandlers(seed))
  return renderWithProviders(<ApiKeysPage />)
}

/** Wiersz siatki zawierający podany tekst (maskę tokenu). */
function rowFor(text: string): HTMLElement {
  const row = screen.getByText(text).closest('[role="row"]')
  if (row === null) throw new Error(`Brak wiersza dla ${text}`)
  return row as HTMLElement
}

describe('ApiKeysPage', () => {
  it('pokazuje adres API serwera z kopiowaniem i linkiem do dokumentacji', async () => {
    const user = userEvent.setup()
    await renderPage()

    const url = `${window.location.origin}/api/v1`
    expect(await screen.findByRole('heading', { name: 'API serwera' })).toBeInTheDocument()
    expect(screen.getByDisplayValue(url)).toBeInTheDocument()

    const docs = screen.getByRole('link', { name: 'Dokumentacja API' })
    expect(docs).toHaveAttribute('href', '/api/docs')
    expect(docs).toHaveAttribute('target', '_blank')
    expect(docs).toHaveAttribute('rel', 'noopener')

    await user.click(screen.getByRole('button', { name: 'Kopiuj adres API' }))
    await expect(navigator.clipboard.readText()).resolves.toBe(url)
    expect(screen.getByRole('button', { name: 'Kopiuj adres API' })).toHaveTextContent('Skopiowano')
  })

  it('pokazuje klucze z maską tokenu i datą utworzenia', async () => {
    await renderPage({ tokens: [makeToken({ token: TOKEN, create_date: CREATE_DATE })] })

    expect(await screen.findByText(MASKED)).toBeInTheDocument()
    const row = rowFor(MASKED)
    expect(within(row).getByText(formatDateTime(CREATE_DATE, 'pl'))).toBeInTheDocument()
    for (const header of ['Nazwa', 'Token', 'Utworzono', 'Akcje']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(header) })).toBeInTheDocument()
    }
    // Pełny token nie może trafić do DOM — widoczna jest wyłącznie maska (kontrakt §T4 pkt 2).
    // Asercja na całym serializowanym HTML, nie tylko tekście: `data-*`, `id`, `aria-*` też (DEC-126).
    expect(document.body.innerHTML).not.toContain(TOKEN)
    // W języku pl wspólny hook `useDataGridLocaleText` ustawia polskie etykiety siatki — stopka
    // paginacji pokazuje „Wierszy na stronę:" (`MuiTablePagination.labelRowsPerPage`) zamiast
    // domyślnego „Rows per page:".
    expect(screen.queryByText('Rows per page:')).not.toBeInTheDocument()
    expect(screen.getByText('Wierszy na stronę:')).toBeInTheDocument()
  })

  it('pokazuje nazwę klucza i „—” w wierszu klucza bez nazwy (V12-3 T2)', async () => {
    await renderPage({
      tokens: [
        makeToken({ token: TOKEN, name: 'Klucz prod' }),
        makeToken({ token: 'ragflow-00000000000000000000000000000002' }),
      ],
    })

    // Klucz z nazwą: komórka zawiera pełną nazwę i `title` (ucięcie to wyłącznie CSS);
    // klucz bez nazwy: „—” w kolumnie Nazwa, nie pusta komórka.
    expect(await screen.findByText('Klucz prod')).toHaveAttribute('title', 'Klucz prod')
    expect(within(rowFor('ragflow-0000…0002')).getByText('—')).toBeInTheDocument()
  })

  it('pokazuje pusty stan, gdy użytkownik nie ma kluczy', async () => {
    await renderPage({ tokens: [] })

    expect(await screen.findByText('Brak kluczy API.')).toBeInTheDocument()
  })

  it('kopiuje pełny token z wiersza i potwierdza to Snackbarem', async () => {
    const user = userEvent.setup()
    await renderPage({ tokens: [makeToken({ token: TOKEN })] })

    await user.click(await screen.findByRole('button', { name: `Kopiuj token ${MASKED}` }))

    await expect(navigator.clipboard.readText()).resolves.toBe(TOKEN)
    // Odzew MINOR z QA-UI E6-2-2: kopiowanie z tabeli ma widoczne potwierdzenie.
    expect(screen.getByTestId('keys-copy-snackbar')).toHaveTextContent('Skopiowano')
  })

  it('porażka kopiowania z wiersza pokazuje błąd w Snackbaru, nie „Skopiowano”', async () => {
    const user = userEvent.setup()
    await renderPage({ tokens: [makeToken({ token: TOKEN })] })
    // HTTP bez `execCommand` (jsdom) = porażka fallbacku `copyToClipboard`.
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })

    await user.click(await screen.findByRole('button', { name: `Kopiuj token ${MASKED}` }))

    expect(screen.getByTestId('keys-copy-snackbar')).toHaveTextContent('Nie udało się skopiować')
    expect(screen.queryByText('Skopiowano')).toBeNull()
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('usuwa klucz po potwierdzeniu w oknie dialogowym', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderPage({ tokens: [makeToken({ token: TOKEN })] })

    await user.click(await screen.findByRole('button', { name: `Usuń klucz ${MASKED}` }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Usunąć klucz?')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(calls).toContain(`DELETE /api/v1/system/tokens/${TOKEN}`))
  })

  it('nie usuwa klucza po anulowaniu potwierdzenia', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderPage({ tokens: [makeToken({ token: TOKEN })] })

    await user.click(await screen.findByRole('button', { name: `Usuń klucz ${MASKED}` }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.some((call) => call.startsWith('DELETE '))).toBe(false)
  })

  it('tworzy klucz i pokazuje pełny token tylko w podglądzie dialogu', async () => {
    const calls = recordRequests()
    const user = userEvent.setup()
    await renderPage({ tokens: [] })
    await screen.findByText('Brak kluczy API.')

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'Nazwa (opcjonalna)' }), 'ci')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    const token = (await screen.findByTestId('settings-new-token')).textContent ?? ''
    expect(token.startsWith('ragflow-')).toBe(true)
    expect(screen.getByText('Skopiuj teraz — nie zobaczysz go ponownie')).toBeInTheDocument()
    expect(calls).toContain('POST /api/v1/system/tokens?name=ci')

    await user.click(within(dialog).getByRole('button', { name: 'Zamknij' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByTestId('settings-new-token')).not.toBeInTheDocument()
    // Nowy klucz wraca z listą; pełny token nie może pozostać w serializowanym HTML (DEC-126).
    expect(document.body.innerHTML).not.toContain(token)
  })

  it('po zamknięciu podglądu pełny token znika z DOM i z cache zapytań', async () => {
    const user = userEvent.setup()
    // POST nadpisany lokalnie: handler T2 dopisuje nowy klucz do listy, a lista z natury rzeczy
    // trzyma tokeny w pełnej postaci (kontrakt §0). Tutaj sprawdzamy sam podgląd — że jego token
    // nie zapisuje się w cache zapytań pod żadnym kluczem (kontrakt §2, §8).
    server.use(...settingsHandlers({ tokens: [] }))
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: { token: 'ragflow-secret01234567890123456789012', create_date: '2025-06-01' },
        }),
      ),
    )
    const { queryClient } = await renderWithProviders(<ApiKeysPage />)
    await screen.findByText('Brak kluczy API.')

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))
    const shown = (await screen.findByTestId('settings-new-token')).textContent ?? ''
    expect(shown).toBe('ragflow-secret01234567890123456789012')

    await user.click(within(dialog).getByRole('button', { name: 'Zamknij' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    expect(screen.queryByText(shown)).not.toBeInTheDocument()
    expect(document.body.innerHTML).not.toContain(shown)
    expect(
      queryClient
        .getQueryCache()
        .getAll()
        .some((query) => JSON.stringify(query.state.data ?? null).includes(shown)),
    ).toBe(false)
  })

  it('pokazuje błąd tworzenia klucza w dialogu', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [] }))
    server.use(
      http.post(apiUrl('/api/v1/system/tokens'), () =>
        HttpResponse.json({ code: 102, message: 'Token limit reached' }),
      ),
    )
    await renderWithProviders(<ApiKeysPage />)

    await user.click(screen.getByRole('button', { name: 'Utwórz klucz' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    expect(
      await within(dialog).findByText('Nie udało się wykonać operacji: Token limit reached'),
    ).toBeInTheDocument()
  })

  it('pokazuje błąd usuwania klucza', async () => {
    const user = userEvent.setup()
    server.use(...settingsHandlers({ tokens: [makeToken({ token: TOKEN })] }))
    server.use(
      http.delete(apiUrl('/api/v1/system/tokens/:token'), () =>
        HttpResponse.json({ code: 102, message: 'Token is in use' }),
      ),
    )
    await renderWithProviders(<ApiKeysPage />)

    await user.click(await screen.findByRole('button', { name: `Usuń klucz ${MASKED}` }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    expect(
      await screen.findByText('Nie udało się wykonać operacji: Token is in use'),
    ).toBeInTheDocument()
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(...settingsHandlers({ tokens: [] }))
    server.use(
      http.get(apiUrl('/api/v1/system/tokens'), () => {
        calls += 1
        if (calls === 1) return HttpResponse.json({ code: 102, message: 'boom' })
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: [makeToken({ token: TOKEN })],
        })
      }),
    )
    const user = userEvent.setup()
    await renderWithProviders(<ApiKeysPage />)

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wykonać operacji: boom',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText(MASKED)).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('na wąskim ekranie akcje są pierwszą kolumną jako menu ⋮', async () => {
    stubNarrowViewport()
    await renderPage({ tokens: [makeToken({ token: TOKEN })] })
    await screen.findByText(MASKED)

    expect(screen.getAllByRole('columnheader')[0]).toHaveAttribute('data-field', 'actions')
    expect(screen.getAllByTestId('row-actions-menu').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: `Usuń klucz ${MASKED}` })).not.toBeInTheDocument()
  })
})
