/**
 * Dialog usuwania bazy z listą powiązań (T4, SC-V12-04): stany pusto/ładowanie/dane/błąd,
 * hidden i truncated, kontener przewijany (>5 pozycji). Trasa usage w MSW:
 * `…datasetUsageHandlers(usage)` albo własny handler (500).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetUsageHandlers,
  fixtureDatasetDetail,
  fixtureDatasetUsage,
  fixtureUsageItem,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DeleteDatasetDialog } from './DeleteDatasetDialog'
import type { DatasetListed } from './queries'

afterEach(cleanup)

// Dialog czyta z bazy tylko `id` i `name` — fixture szczegółu wystarcza (rzutowanie jak w queries.ts).
const DATASET = fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa' }) as unknown as DatasetListed

function renderDialog() {
  return renderWithProviders(
    <DeleteDatasetDialog
      dataset={DATASET}
      loading={false}
      onConfirm={() => {}}
      onCancel={() => {}}
    />,
  )
}

function dialog() {
  return screen.getByRole('dialog')
}

function confirm() {
  return within(dialog()).getByTestId('delete-dataset-confirm')
}

describe('DeleteDatasetDialog', () => {
  it('baza bez powiązań — dialog bez sekcji, przycisk „Usuń” aktywny', async () => {
    await renderDialog()

    expect(dialog()).toHaveTextContent('Czy usunąć bazę wiedzy „Alfa”?')
    // Po dojściu (pustego) usage: szkielet i sekcja znikają, potwierdzenie aktywne.
    await waitFor(() => expect(confirm()).toBeEnabled())
    expect(confirm()).toHaveTextContent('Usuń')
    expect(screen.queryByTestId('delete-dataset-usage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('delete-dataset-usage-loading')).not.toBeInTheDocument()
  })

  it('ładowanie powiązań — szkielet w sekcji, przycisk nieaktywny', async () => {
    server.use(
      // Żądanie wiszące (wzór: `ExportDialog.test.tsx`) — stan ładowania do końca testu.
      http.get(apiUrl('/api/wd/v1/datasets/:datasetId/usage'), () => new Promise(() => undefined)),
    )
    await renderDialog()

    expect(await screen.findByTestId('delete-dataset-usage-loading')).toBeInTheDocument()
    expect(confirm()).toBeDisabled()
  })

  it('dane — nazwy zwykłym tekstem (bez linków) i „Usuń mimo to”', async () => {
    server.use(
      ...datasetUsageHandlers(
        fixtureDatasetUsage({
          chats: [fixtureUsageItem('Czat GUS'), fixtureUsageItem('Czat Wawel')],
          searches: [fixtureUsageItem('Wyszukiwarka GUS')],
        }),
      ),
    )
    await renderDialog()

    const usage = await screen.findByTestId('delete-dataset-usage')
    expect(within(usage).getByText('Czaty (2):')).toBeInTheDocument()
    const chats = within(usage).getByTestId('delete-dataset-usage-chats')
    expect(chats).toHaveTextContent('Czat GUS')
    expect(chats).toHaveTextContent('Czat Wawel')
    expect(within(usage).getByTestId('delete-dataset-usage-searches')).toHaveTextContent(
      'Wyszukiwarka GUS',
    )
    expect(within(chats).queryAllByRole('link')).toHaveLength(0)
    expect(confirm()).toHaveTextContent('Usuń mimo to')
    expect(within(usage).getByText('Po usunięciu te czaty i wyszukiwarki stracą to źródło.'))
  })

  it('powiązania ukryte — „…oraz 1 czat innego użytkownika”, odmiana 5 (many)', async () => {
    server.use(
      ...datasetUsageHandlers(fixtureDatasetUsage({ hidden_chats: 1, hidden_searches: 5 })),
    )
    await renderDialog()

    const hidden = await screen.findByTestId('delete-dataset-usage-hidden')
    expect(hidden).toHaveTextContent('…oraz 1 czat innego użytkownika')
    expect(hidden).toHaveTextContent('…oraz 5 wyszukiwarek innych użytkowników')
    expect(confirm()).toHaveTextContent('Usuń mimo to')
  })

  it('truncated — dodatkowy wiersz „…i więcej”', async () => {
    server.use(
      ...datasetUsageHandlers(
        fixtureDatasetUsage({
          chats: Array.from({ length: 6 }, (_, index) => fixtureUsageItem(`Czat #${index + 1}`)),
          truncated: true,
        }),
      ),
    )
    await renderDialog()

    expect(await screen.findByText('…i więcej')).toBeInTheDocument()
    expect(confirm()).toHaveTextContent('Usuń mimo to')
  })

  it('błąd trasy usage (500) — komunikat, przycisk „Usuń” aktywny', async () => {
    server.use(
      http.get(apiUrl('/api/wd/v1/datasets/:datasetId/usage'), () =>
        HttpResponse.json({ error: { code: 'internal', message: 'boom' } }, { status: 500 }),
      ),
    )
    await renderDialog()

    expect(await screen.findByTestId('delete-dataset-usage-error')).toHaveTextContent(
      'Nie udało się sprawdzić powiązań',
    )
    expect(confirm()).toBeEnabled()
    expect(confirm()).toHaveTextContent('Usuń')
  })

  it('>5 pozycji — lista czatów ma przewijacz z maxHeight 40vh', async () => {
    server.use(
      ...datasetUsageHandlers(
        fixtureDatasetUsage({
          chats: Array.from({ length: 7 }, (_, index) => fixtureUsageItem(`Czat #${index + 1}`)),
        }),
      ),
    )
    await renderDialog()

    const chats = await screen.findByTestId('delete-dataset-usage-chats')
    const style = getComputedStyle(chats)
    expect(style.overflowY).toBe('auto')
    // jsdom rozwiązuje `40vh` na piksele (40 % wysokości okna) — asercja jak w e2e (SC-V12-04).
    expect(Number.parseFloat(style.maxHeight)).toBeLessThanOrEqual(window.innerHeight * 0.4 + 1)
  })

  // T8 (review T6): podpowiedź przewijania tylko przy przepełnionej liście. W jsdom
  // `scrollHeight` = 0, więc pomiar przepełnienia tu nie działa — sprawdzalny jest brak
  // podpowiedzi dla krótkiej listy; widoczność przy przepełnieniu pilnuje e2e (SC-V12-04).
  it('lista mieszcząca się — brak podpowiedzi przewijania', async () => {
    server.use(
      ...datasetUsageHandlers(
        fixtureDatasetUsage({
          chats: [fixtureUsageItem('Czat GUS'), fixtureUsageItem('Czat Wawel')],
        }),
      ),
    )
    await renderDialog()

    await screen.findByTestId('delete-dataset-usage-chats')
    expect(screen.queryByTestId('delete-dataset-usage-scrollhint')).not.toBeInTheDocument()
  })
})
