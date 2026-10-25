import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { RetrievalTab } from './RetrievalTab'
import type { SettingsCardProps } from './SettingsCard'

// Karta ustawień jest w T1 atrapą bez przycisku Uruchom, więc test wystawia `onRun` obok
// prawdziwej atrapy (kontrakt §RetrievalTab: kartę podmienia T2). Testid atrapy zostaje —
// asercja niżej sprawdza realny plik `SettingsCard.tsx`.
vi.mock('./SettingsCard', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./SettingsCard')>()
  return {
    ...actual,
    SettingsCard: (props: SettingsCardProps) => (
      <>
        <actual.SettingsCard {...props} />
        <button type="button" data-testid="stub-run" onClick={props.onRun} />
      </>
    ),
  }
})

afterEach(cleanup)

describe('RetrievalTab', () => {
  it('składa kartę ustawień i kartę wyników', async () => {
    await renderWithProviders(<RetrievalTab datasetId="ds-1" />)

    expect(screen.getByTestId('retrieval-settings-card')).toBeInTheDocument()
    // Karta wyników jest już prawdziwa (T3) — atrapy `results-card-stub` nie ma; bez wyniku
    // pokazuje tytuł karty i pusty stan „nie uruchomiono”.
    expect(screen.getByText('Wyniki')).toBeInTheDocument()
    expect(
      screen.getByText('Nie uruchomiono jeszcze testu. Wpisz pytanie i kliknij Uruchom.'),
    ).toBeInTheDocument()
  })

  it('pokazuje powiadomienie o błędzie, gdy żądanie kończy się błędem 500', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(apiUrl('/api/v1/retrieval'), () =>
        HttpResponse.json({ code: 1, message: 'boom' }, { status: 500 }),
      ),
    )

    await renderWithProviders(<RetrievalTab datasetId="ds-1" />)
    await user.click(screen.getByTestId('stub-run'))

    expect(await screen.findByText('Nie udało się uruchomić testu retrievalu.')).toBeInTheDocument()
  })
})
