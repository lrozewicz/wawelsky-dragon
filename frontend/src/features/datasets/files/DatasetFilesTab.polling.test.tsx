/**
 * Polling zakładki Pliki (kontrakt WP E3-3b §T5): lista w stanie parsowania odświeża się co 3 s
 * (`refetchInterval` z `documentsListQueryOptions`), a po zakończeniu przestaje.
 * Osobny plik od `DatasetFilesTab.test.tsx`, bo korzysta z fałszywego zegara.
 */

import { act, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { initI18n } from '../../../i18n'
import { documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'
import { POLL_INTERVAL_MS } from './queries'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const CHUNKS_ROUTE = '/chunk/parsed/chunks'

describe('DatasetFilesTab — polling', () => {
  it('odpytuje listę co 3 s, dopóki dokument się parsuje', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers(
        [fixtureDocument({ id: 'doc-1', name: 'duzy.pdf', run: 'RUNNING', progress: 0.3 })],
        {
          onRequest: (kind, _body, url) => {
            if (kind === 'list') seen.push(url)
          },
        },
      ),
    )

    // Pakiet tłumaczeń ładujemy przed fałszywym zegarem — inaczej dynamika `import()` czeka na timer.
    await initI18n('pl')
    vi.useFakeTimers()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(seen).toHaveLength(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(seen).toHaveLength(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(seen).toHaveLength(3)
  })

  it('przy zakończonym parsowaniu nie odpytuje ponownie', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers(
        [fixtureDocument({ id: 'doc-1', name: 'gotowy.pdf', run: 'DONE', progress: 1 })],
        {
          onRequest: (kind, _body, url) => {
            if (kind === 'list') seen.push(url)
          },
        },
      ),
    )

    await initI18n('pl')
    vi.useFakeTimers()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(seen).toHaveLength(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    })
    expect(seen).toHaveLength(1)
  })
})
