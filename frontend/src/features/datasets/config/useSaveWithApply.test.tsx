/**
 * Testy `useSaveWithApply` (kontrakt WP E6-1b §2, uzupełnienie E5-H8c): po zapisie datasetu
 * dialog pyta o istniejące pliki również przy zmianie `enable_metadata` i listy pól `metadata`.
 * `metadata` porównujemy strukturalnie — świeży obiekt z formularza nie może udawać zmiany.
 */

import { renderHook } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import { documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { initI18n } from '../../../i18n'

import { useSaveWithApply } from './useSaveWithApply'

function withDocuments(count: number): void {
  server.use(
    ...documentsHandlers(
      Array.from({ length: count }, (_, i) => fixtureDocument({ id: `doc-${i}` })),
    ),
  )
}

beforeEach(async () => {
  await initI18n('pl')
  withDocuments(1)
})

describe('useSaveWithApply — metadane', () => {
  it('zmiana enable_metadata i listy pól otwiera dialog z etykietami metadanych', async () => {
    const { result } = renderHook(() => useSaveWithApply('ds-1'))

    await act(async () => {
      await result.current.open(
        { parser_config: { enable_metadata: true, metadata: [{ key: 'rok' }] } },
        { enable_metadata: false, metadata: [] },
      )
    })

    expect(result.current.request?.parserConfigChanges).toEqual({
      enable_metadata: true,
      metadata: [{ key: 'rok' }],
    })
    expect(result.current.request?.changedLabels).toEqual(['Auto-metadane', 'Pola metadanych'])
  })

  it('ta sama lista pól w innej referencji nie jest zmianą', async () => {
    const { result } = renderHook(() => useSaveWithApply('ds-1'))

    await act(async () => {
      await result.current.open(
        { parser_config: { metadata: [{ key: 'rok' }] } },
        { metadata: [{ key: 'rok' }] },
      )
    })

    expect(result.current.request).toBeNull()
  })

  it('brak dokumentów nie otwiera dialogu mimo zmiany metadanych', async () => {
    withDocuments(0)
    const { result } = renderHook(() => useSaveWithApply('ds-1'))

    await act(async () => {
      await result.current.open({ parser_config: { enable_metadata: true } }, {})
    })

    expect(result.current.request).toBeNull()
  })
})
