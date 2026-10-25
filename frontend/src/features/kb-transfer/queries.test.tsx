import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'

import { resetKbTransfer } from '../../test/msw/handlers'
import { WdApiError } from '../admin/wdClient'

import {
  kbTransferKeys,
  useCreateImport,
  useDeleteImport,
  useExportPreview,
  useStartExport,
  useStartImport,
  useStopTask,
} from './queries'

afterEach(cleanup)

beforeEach(() => {
  resetKbTransfer()
})

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

/** Uruchamia mutację w `act` i oddaje jej wynik. */
async function actMutate<T>(run: () => Promise<T>): Promise<T> {
  let out!: T
  await act(async () => {
    out = await run()
  })
  return out
}

describe('useExportPreview', () => {
  it('z `enabled: false` nie pyta backendu i nie ma danych', () => {
    const client = createClient()
    const hook = renderHook(() => useExportPreview('d1', false), { wrapper: wrapperFor(client) })

    expect(hook.result.current.fetchStatus).toBe('idle')
    expect(hook.result.current.data).toBeUndefined()
    expect(client.getQueryState(kbTransferKeys.exportPreview('d1'))?.fetchStatus).toBe('idle')
  })

  it('z `enabled: true` wczytuje podgląd pod kluczem [kb-transfer, export-preview, id]', async () => {
    const client = createClient()
    const hook = renderHook(() => useExportPreview('d1', true), { wrapper: wrapperFor(client) })

    await waitFor(() => {
      expect(hook.result.current.data?.chunks).toBe(7251)
    })
    expect(hook.result.current.data?.name).toBe('Rocznik GUS 2024')
    expect(client.getQueryData(kbTransferKeys.exportPreview('d1'))).toEqual(
      hook.result.current.data,
    )
  })

  it('błąd trasy zostaje w stanie zapytania (kod `not_found`)', async () => {
    const client = createClient()
    const hook = renderHook(() => useExportPreview('obcy', true), { wrapper: wrapperFor(client) })

    await waitFor(() => {
      expect(hook.result.current.error).toBeInstanceOf(WdApiError)
    })
    expect((hook.result.current.error as WdApiError).code).toBe('not_found')
  })
})

describe('mutacje', () => {
  it('useStartExport oddaje referencję zadania, a drugi start — błąd z details.task_id', async () => {
    const client = createClient()
    const hook = renderHook(() => useStartExport(), { wrapper: wrapperFor(client) })

    const ref = await actMutate(() =>
      hook.result.current.mutateAsync({ datasetId: 'd1', includeVectors: true }),
    )
    expect(ref.status).toBe('queued')

    await act(async () => {
      await expect(
        hook.result.current.mutateAsync({ datasetId: 'd1', includeVectors: false }),
      ).rejects.toMatchObject({
        code: 'export_in_progress',
        details: { task_id: ref.task_id },
      })
    })
    expect(hook.result.current.error).toMatchObject({ code: 'export_in_progress' })
  })

  it('useStopTask i useDeleteImport zwracają odpowiedzi backendu', async () => {
    const client = createClient()
    const start = renderHook(() => useStartExport(), { wrapper: wrapperFor(client) })
    const stop = renderHook(() => useStopTask(), { wrapper: wrapperFor(client) })
    const remove = renderHook(() => useDeleteImport(), { wrapper: wrapperFor(client) })
    const create = renderHook(() => useCreateImport(), { wrapper: wrapperFor(client) })

    const ref = await actMutate(() =>
      start.result.current.mutateAsync({ datasetId: 'd1', includeVectors: true }),
    )
    await expect(actMutate(() => stop.result.current.mutateAsync(ref.task_id))).resolves.toEqual({
      stopped: true,
    })

    const session = await actMutate(() =>
      create.result.current.mutateAsync({ fileName: 'paczka.wdkb.zip', sizeBytes: 6 }),
    )
    await expect(
      actMutate(() => remove.result.current.mutateAsync(session.import_id)),
    ).resolves.toEqual({ deleted: true })
  })

  it('useStartImport przed walidacją paczki daje 409 import_not_ready', async () => {
    const client = createClient()
    const create = renderHook(() => useCreateImport(), { wrapper: wrapperFor(client) })
    const start = renderHook(() => useStartImport(), { wrapper: wrapperFor(client) })

    const session = await actMutate(() =>
      create.result.current.mutateAsync({ fileName: 'paczka.wdkb.zip', sizeBytes: 6 }),
    )
    // Sesja nie jest jeszcze po walidacji — backend odpowiada 409 `import_not_ready`.
    await act(async () => {
      await expect(
        start.result.current.mutateAsync({
          importId: session.import_id,
          name: 'Kopia',
          embeddingModel: null,
        }),
      ).rejects.toMatchObject({ code: 'import_not_ready', details: { state: 'uploading' } })
    })
  })
})
