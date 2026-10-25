/**
 * Mutacje warstwy danych plików (kontrakt WP E4-5c §2). Handlery MSW definiowane lokalnie —
 * T1b pisze `test/msw/handlers/files.ts` równolegle, więc go nie importujemy.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { ApiError } from '../../api/envelope'
import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { datasetKeys } from '../datasets/queries'

import {
  useCreateFolder,
  useDeleteFiles,
  useLinkFiles,
  useMoveFiles,
  useRenameFile,
} from './mutations'
import { DEFAULT_FILES_QUERY, fileKeys } from './queries'

afterEach(cleanup)

const createdFolder = {
  created_by: 'u-1',
  id: 'folder-new',
  location: '',
  name: 'N',
  parent_id: 'root-1',
  size: 0,
  source_type: 'local',
  tenant_id: 't-1',
  type: 'folder',
}

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderMutations(client: QueryClient) {
  return renderHook(
    () => ({
      createFolder: useCreateFolder(),
      move: useMoveFiles(),
      rename: useRenameFile(),
      link: useLinkFiles(),
      remove: useDeleteFiles(),
    }),
    { wrapper: wrapperFor(client) },
  )
}

function isInvalidated(client: QueryClient, key: readonly unknown[]): boolean {
  return client.getQueryState(key)?.isInvalidated === true
}

describe('mutacje plików', () => {
  it('wysyła ciała żądań zgodne z trasami /files', async () => {
    const calls: { url: string; body: unknown }[] = []
    server.use(
      http.post(apiUrl('/api/v1/files'), async ({ request }) => {
        calls.push({ url: request.url, body: await request.json() })
        return HttpResponse.json({ code: 0, message: 'success', data: createdFolder })
      }),
      http.post(apiUrl('/api/v1/files/move'), async ({ request }) => {
        calls.push({ url: request.url, body: await request.json() })
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
      http.post(apiUrl('/api/v1/files/link-to-datasets'), async ({ request }) => {
        calls.push({ url: request.url, body: await request.json() })
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await result.current.createFolder.mutateAsync({ name: 'N', parentId: 'p' })
      await result.current.rename.mutateAsync({ id: 'a', newName: 'b.txt' })
      await result.current.move.mutateAsync({ srcIds: ['a'], destId: 'd' })
      await result.current.link.mutateAsync({ fileIds: ['a'], kbIds: ['ds-1'] })
    })

    expect(calls.map((call) => new URL(call.url).pathname)).toEqual([
      '/api/v1/files',
      '/api/v1/files/move',
      '/api/v1/files/move',
      '/api/v1/files/link-to-datasets',
    ])
    expect(calls[0]?.body).toEqual({ name: 'N', type: 'folder', parent_id: 'p' })
    expect(calls[1]?.body).toEqual({ src_file_ids: ['a'], new_name: 'b.txt' })
    expect(calls[2]?.body).toEqual({ src_file_ids: ['a'], dest_file_id: 'd' })
    expect(calls[3]?.body).toEqual({ file_ids: ['a'], kb_ids: ['ds-1'] })
    expect(new URL(calls[3]!.url).searchParams.get('mode')).toBeNull()
  })

  it('pomija parent_id, gdy nie podano folderu nadrzędnego', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post(apiUrl('/api/v1/files'), async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ code: 0, message: 'success', data: createdFolder })
      }),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await result.current.createFolder.mutateAsync({ name: 'N', parentId: undefined })
    })

    expect(bodies).toEqual([{ name: 'N', type: 'folder' }])
  })

  it('wysyła mode w query tylko gdy podany', async () => {
    const urls: string[] = []
    server.use(
      http.post(apiUrl('/api/v1/files/link-to-datasets'), ({ request }) => {
        urls.push(request.url)
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await result.current.link.mutateAsync({ fileIds: ['a'], kbIds: ['ds-1'], mode: 'replace' })
      await result.current.link.mutateAsync({ fileIds: ['a'], kbIds: ['ds-1'], mode: 'add' })
    })

    expect(new URL(urls[0]!).searchParams.get('mode')).toBe('replace')
    expect(new URL(urls[1]!).searchParams.get('mode')).toBe('add')
  })

  it('usuwa częściowo (102) bez rzutu: licznik i błędy z koperty', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({
          code: 102,
          message: 'Deleted files failed with 1 errors',
          data: { success_count: 1, errors: ['File or Folder not found: b'] },
        }),
      ),
    )
    const { result } = renderMutations(createClient())
    let outcome: unknown

    await act(async () => {
      outcome = await result.current.remove.mutateAsync({ ids: ['a', 'b'] })
    })

    expect(outcome).toEqual({ successCount: 1, errors: ['File or Folder not found: b'] })
    expect(result.current.remove.error).toBeNull()
  })

  it('pełny sukces (0) zwraca licznik bez błędów', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: { success_count: 2 } }),
      ),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await expect(result.current.remove.mutateAsync({ ids: ['a', 'b'] })).resolves.toEqual({
        successCount: 2,
        errors: [],
      })
    })
  })

  it('inne code≠0 rzuca ApiError z komunikatem koperty', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 100, message: 'x', data: null }),
      ),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await expect(result.current.remove.mutateAsync({ ids: ['a'] })).rejects.toBeInstanceOf(
        ApiError,
      )
    })
    await act(async () => {
      await expect(result.current.remove.mutateAsync({ ids: ['a'] })).rejects.toMatchObject({
        code: 100,
        message: 'x',
      })
    })
  })

  it('koperta błędu bez komunikatu i z HTTP 401 rzuca ApiError ze statusem', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/files'), () => HttpResponse.json({ code: 100 }, { status: 401 })),
    )
    const { result } = renderMutations(createClient())

    await act(async () => {
      await expect(result.current.remove.mutateAsync({ ids: ['a'] })).rejects.toMatchObject({
        code: 100,
        message: '',
        httpStatus: 401,
      })
    })
  })

  it('po sukcesie unieważnia fileKeys.all, a link dodatkowo datasetKeys.all', async () => {
    server.use(
      http.post(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: createdFolder }),
      ),
      http.post(apiUrl('/api/v1/files/link-to-datasets'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: true }),
      ),
    )
    const client = createClient()
    const { result } = renderMutations(client)

    client.setQueryData(fileKeys.list(DEFAULT_FILES_QUERY), { files: [], total: 0 })
    client.setQueryData(datasetKeys.list(), [])
    await act(async () => {
      await result.current.createFolder.mutateAsync({ name: 'N', parentId: undefined })
    })
    expect(isInvalidated(client, fileKeys.list(DEFAULT_FILES_QUERY))).toBe(true)
    expect(isInvalidated(client, datasetKeys.list())).toBe(false)

    client.clear()
    client.setQueryData(fileKeys.list(DEFAULT_FILES_QUERY), { files: [], total: 0 })
    client.setQueryData(datasetKeys.list(), [])
    await act(async () => {
      await result.current.link.mutateAsync({ fileIds: ['a'], kbIds: ['ds-1'] })
    })
    expect(isInvalidated(client, fileKeys.list(DEFAULT_FILES_QUERY))).toBe(true)
    expect(isInvalidated(client, datasetKeys.list())).toBe(true)
  })
})
