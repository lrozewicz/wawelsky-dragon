/**
 * Integracja sekcji „Metadane” z zakładką „Konfiguracja” (kontrakt WP E6-1b §1/§4): kolejność
 * zapisu (najpierw PUT `…/metadata/config`, potem PUT datasetu z `parser_config` niosącym nową
 * listę i `enable_metadata`), błąd zapisu pól (komunikat, pola zostają, PUT datasetu nie idzie),
 * dialog „Zastosować zmiany…” po zmianie listy pól, blokada „Zapisz” przy duplikacie klucza
 * i reset „Anuluj”.
 */
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  documentsHandlers,
  fixtureDatasetDetail,
  fixtureDocument,
  metadataHandlers,
} from '../../../test/msw/handlers'
import type { FixtureMetadataField } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { Dataset } from '../queries'

import { ConfigurationTab } from './ConfigurationTab'

afterEach(cleanup)

/** Atrapa MSW to podzbiór `DatasetDetail` — jak w `ConfigurationTab.test.tsx`. */
function dataset(overrides: Record<string, unknown> = {}): Dataset {
  return fixtureDatasetDetail(overrides) as unknown as Dataset
}

/** Pole `rok` w kształcie drutu — nasienie konfiguracji metadanych w atrapie. */
const rokField: FixtureMetadataField = { key: 'rok', type: 'string', description: null, enum: null }

/** Przechwytuje ciała obu PUT-ów w kolejności wywołań (wzór: `captureUpdate` w T4 E3-3a). */
function captureSaves() {
  const calls: string[] = []
  const metaBody: { current: { metadata?: FixtureMetadataField[] } | null } = { current: null }
  const datasetBody: { current: Record<string, unknown> | null } = { current: null }
  server.use(
    ...datasetHandlers([fixtureDatasetDetail()], {
      onUpdate: (body) => {
        calls.push('dataset')
        datasetBody.current = body
      },
    }),
    ...metadataHandlers(
      {},
      {
        onUpdate: (_datasetId, body) => {
          calls.push('meta')
          metaBody.current = body
        },
      },
    ),
  )
  return { calls, metaBody, datasetBody }
}

/** Wypełnia sekcję „Metadane”: jeden wiersz `rok` z opisem i włączonymi auto-metadanymi. */
async function fillRokField(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  // Sekcja renderuje się po wczytaniu `…/metadata/config` — najpierw czekamy na przycisk.
  await screen.findByRole('button', { name: '+ Pole' })
  await user.click(screen.getByRole('button', { name: '+ Pole' }))
  const row = screen.getByRole('group', { name: 'Pole 1' })
  await user.type(within(row).getByLabelText('Klucz'), 'rok')
  await user.type(within(row).getByLabelText('Opis'), 'Rok, którego dotyczą dane')
  await user.click(screen.getByRole('switch', { name: 'Auto-metadane' }))
}

describe('ConfigurationTab — sekcja Metadane', () => {
  it('zapis idzie w kolejności: PUT metadata/config, potem PUT datasetu z parser_config', async () => {
    const captured = captureSaves()
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await fillRokField(user)
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Zapisano')).toBeInTheDocument()
    expect(captured.calls).toEqual(['meta', 'dataset'])
    expect(captured.metaBody.current).toEqual({
      metadata: [
        { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
      ],
    })
    const parserConfig = captured.datasetBody.current?.parser_config as Record<string, unknown>
    expect(parserConfig.enable_metadata).toBe(true)
    // PUT datasetu niesie NOWĄ listę pól — nie nadpisze zapisu metadata/config (kontrakt §1).
    expect(parserConfig.metadata).toEqual([
      { key: 'rok', type: 'string', description: 'Rok, którego dotyczą dane', enum: null },
    ])
    // Po sukcesie nic do zapisania (bazą jest dataset z odpowiedzi PUT).
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('błąd zapisu pól: komunikat przy polu (nie alert karty), pola zostają, PUT datasetu nie wychodzi', async () => {
    const datasetBody: { current: Record<string, unknown> | null } = { current: null }
    server.use(
      ...datasetHandlers([fixtureDatasetDetail()], {
        onUpdate: (body) => {
          datasetBody.current = body
        },
      }),
      // Awaria PUT `…/metadata/config`: koperta HTTP 200 + `code ≠ 0` — UI widzi `ApiError`.
      http.put(apiUrl('/api/v1/datasets/:datasetId/metadata/config'), () =>
        HttpResponse.json({ code: 500, message: 'E2E: awaria zapisu metadanych', data: null }),
      ),
    )
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await fillRokField(user)
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    const row = screen.getByRole('group', { name: 'Pole 1' })
    expect(await within(row).findByText('E2E: awaria zapisu metadanych')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(within(row).getByLabelText('Klucz')).toHaveValue('rok')
    expect(within(row).getByLabelText('Opis')).toHaveValue('Rok, którego dotyczą dane')
    expect(screen.getByRole('switch', { name: 'Auto-metadane' })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeEnabled()
    expect(datasetBody.current).toBeNull()
  })

  it('zapis przy dokumentach otwiera dialog „Zastosować zmiany…” z etykietami metadanych', async () => {
    captureSaves()
    server.use(...documentsHandlers([fixtureDocument()]))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    await fillRokField(user)
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    const dialog = await screen.findByRole('dialog', {
      name: 'Zastosować zmiany do istniejących plików?',
    })
    expect(dialog).toHaveTextContent('Auto-metadane')
    expect(dialog).toHaveTextContent('Pola metadanych')
    expect(within(dialog).getByRole('button', { name: 'Tylko nowe pliki' })).toBeEnabled()
  })

  it('duplikat klucza wyłącza „Zapisz”', async () => {
    server.use(...metadataHandlers({ 'ds-1': [rokField] }))
    const user = userEvent.setup()
    await renderWithProviders(<ConfigurationTab dataset={dataset()} />)

    const existing = await screen.findByRole('group', { name: 'Pole 1' })
    expect(within(existing).getByLabelText('Klucz')).toHaveValue('rok')
    await user.click(screen.getByRole('button', { name: '+ Pole' }))
    await user.type(
      within(screen.getByRole('group', { name: 'Pole 2' })).getByLabelText('Klucz'),
      'rok',
    )

    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })

  it('„Anuluj” przywraca pola z zapisanego stanu datasetu', async () => {
    server.use(...metadataHandlers({ 'ds-1': [rokField] }))
    const user = userEvent.setup()
    // W realnej aplikacji `parser_config.metadata` datasetu to to samo źródło co GET
    // `…/metadata/config` — atrapa datasetu je niesie, żeby reset „Anuluj” był wierny.
    await renderWithProviders(
      <ConfigurationTab dataset={dataset({ parser_config: { metadata: [rokField] } })} />,
    )

    const row = await screen.findByRole('group', { name: 'Pole 1' })
    await user.clear(within(row).getByLabelText('Klucz'))
    await user.type(within(row).getByLabelText('Klucz'), 'rok2')
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(
      within(screen.getByRole('group', { name: 'Pole 1' })).getByLabelText('Klucz'),
    ).toHaveValue('rok')
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()
  })
})
