/**
 * Liczba mnoga plików na kartach baz wiedzy (kontrakt WP E3-H2a §K6, MINOR E3-3b):
 * polskie formy i18next `files_one/_few/_many/_other` — 1 plik, 2/22 pliki, 5 plików —
 * oraz angielskie `1 file` / `2 files`.
 */

import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { datasetHandlers, fixtureDatasetDetail } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DatasetsPage } from './DatasetsPage'

afterEach(cleanup)

const ROUTES = ['/datasets', '/dataset/files/$id']

/** Fabryka kart z zadaną liczbą plików — nazwy nieistotne, liczy się tekst z odmianą. */
function datedDataset(id: string, documentCount: number) {
  return fixtureDatasetDetail({ id, name: `Baza ${id}`, document_count: documentCount })
}

async function renderCounts(counts: number[], language: 'pl' | 'en') {
  server.use(
    ...datasetHandlers(counts.map((count, index) => datedDataset(`ds-${String(index)}`, count))),
  )
  await renderWithProviders(<DatasetsPage />, { routes: ROUTES, language })
  await screen.findAllByTestId('dataset-card')
}

describe('DatasetsPage — liczba mnoga plików', () => {
  it('polski odmienia: 1 plik, 2 pliki, 5 plików, 22 pliki', async () => {
    await renderCounts([1, 2, 5, 22], 'pl')

    for (const expected of ['1 plik', '2 pliki', '5 plików', '22 pliki']) {
      expect(screen.getByText(expected)).toBeInTheDocument()
    }
  })

  it('angielski używa form file/files', async () => {
    await renderCounts([1, 2], 'en')

    expect(screen.getByText('1 file')).toBeInTheDocument()
    expect(screen.getByText('2 files')).toBeInTheDocument()
  })
})
