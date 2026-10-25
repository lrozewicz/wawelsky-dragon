/**
 * Zapytania warstwy danych plików (kontrakt WP E4-5c §1). Handlery MSW definiowane lokalnie —
 * T1b pisze `test/msw/handlers/files.ts` równolegle, więc go nie importujemy.
 */

import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/envelope'
import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  DEFAULT_FILES_QUERY,
  ancestorsQueryOptions,
  fileKeys,
  filesListQueryOptions,
  folderChildrenQueryOptions,
  type FileItem,
  type FileParent,
} from './queries'

function fileItem(over: Partial<FileItem> = {}): FileItem {
  return {
    create_date: '2026-01-01T00:00:00',
    create_time: 1767225600,
    created_by: 'u-1',
    id: 'file-1',
    kbs_info: [],
    location: '',
    name: 'notatki.txt',
    parent_id: 'root-1',
    size: 1234,
    source_type: 'local',
    tenant_id: 't-1',
    type: 'file',
    update_date: '2026-01-01T00:00:00',
    update_time: 1767225600,
    ...over,
  }
}

function fileParent(over: Partial<FileParent> = {}): FileParent {
  return {
    create_date: '2026-01-01T00:00:00',
    create_time: 1767225600,
    created_by: 'u-1',
    id: 'folder-1',
    location: '',
    name: 'Projekty',
    parent_id: 'root-1',
    size: 0,
    source_type: 'local',
    tenant_id: 't-1',
    type: 'folder',
    update_date: '2026-01-01T00:00:00',
    update_time: 1767225600,
    ...over,
  }
}

function listEnvelope(files: FileItem[], total = files.length) {
  return { code: 0, message: 'success', data: { files, parent_folder: fileParent(), total } }
}

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('filesListQueryOptions', () => {
  it('wysyła stronę i sortowanie, pomija puste filtry, a z nimi parent_id i keywords', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/files'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json(listEnvelope([]))
      }),
    )
    const client = createClient()

    await client.fetchQuery(filesListQueryOptions(DEFAULT_FILES_QUERY))
    await client.fetchQuery(
      filesListQueryOptions({ ...DEFAULT_FILES_QUERY, parentId: 'f1', keywords: 'abc' }),
    )

    const plain = seen[0]?.searchParams
    expect(plain?.get('page')).toBe('1')
    expect(plain?.get('page_size')).toBe('15')
    expect(plain?.get('orderby')).toBe('create_time')
    expect(plain?.get('desc')).toBe('true')
    expect(plain?.get('parent_id')).toBeNull()
    expect(plain?.get('keywords')).toBeNull()

    const filtered = seen[1]?.searchParams
    expect(filtered?.get('parent_id')).toBe('f1')
    expect(filtered?.get('keywords')).toBe('abc')
  })

  it('zwraca pliki, liczbę i folder nadrzędny; klucz i placeholderData z kontraktu', async () => {
    server.use(
      http.get(apiUrl('/api/v1/files'), () =>
        HttpResponse.json(listEnvelope([fileItem({ id: 'file-1' }), fileItem({ id: 'file-2' })])),
      ),
    )

    const result = await createClient().fetchQuery(filesListQueryOptions(DEFAULT_FILES_QUERY))

    expect(result.files.map((f) => f.id)).toEqual(['file-1', 'file-2'])
    expect(result.total).toBe(2)
    expect(result.parentFolder.id).toBe('folder-1')
    const options = filesListQueryOptions(DEFAULT_FILES_QUERY)
    expect(options.queryKey).toEqual(fileKeys.list(DEFAULT_FILES_QUERY))
    expect(options.placeholderData).toBeDefined()
    expect(fileKeys.all).toEqual(['files'])
  })

  it('koperta code≠0 rzuca ApiError', async () => {
    server.use(
      http.get(apiUrl('/api/v1/files'), () =>
        HttpResponse.json({ code: 100, message: 'błąd listy', data: null }),
      ),
    )

    await expect(
      createClient().fetchQuery(filesListQueryOptions(DEFAULT_FILES_QUERY)),
    ).rejects.toBeInstanceOf(ApiError)
  })
})

describe('ancestorsQueryOptions', () => {
  it('odwraca kolejność z API na root → bieżący', async () => {
    server.use(
      http.get(apiUrl('/api/v1/files/:fileId/ancestors'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: {
            parent_folders: [
              fileParent({ id: 'f2' }),
              fileParent({ id: 'f1' }),
              fileParent({ id: 'root' }),
            ],
          },
        }),
      ),
    )

    const result = await createClient().fetchQuery(ancestorsQueryOptions('f2'))

    expect(result.map((p) => p.id)).toEqual(['root', 'f1', 'f2'])
    expect(ancestorsQueryOptions('f2').queryKey).toEqual(fileKeys.ancestors('f2'))
  })

  it('dla undefined ma klucz root i nie odpytuje API', async () => {
    const resolver = vi.fn(() =>
      HttpResponse.json({ code: 0, message: 'success', data: { parent_folders: [] } }),
    )
    server.use(http.get(apiUrl('/api/v1/files/:fileId/ancestors'), resolver))
    const options = ancestorsQueryOptions(undefined)

    expect(options.queryKey).toEqual(fileKeys.ancestors('root'))
    expect(options.enabled).toBe(false)

    const { result } = renderHook(() => useQuery(options), {
      wrapper: wrapperFor(createClient()),
    })
    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(resolver).not.toHaveBeenCalled()
  })
})

describe('folderChildrenQueryOptions', () => {
  it('pyta o 1000 pozycji po nazwie i zwraca tylko foldery', async () => {
    const seen: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/files'), ({ request }) => {
        seen.push(new URL(request.url))
        return HttpResponse.json(
          listEnvelope([fileItem({ id: 'folder-1', type: 'folder' }), fileItem()]),
        )
      }),
    )
    const client = createClient()

    const rootChildren = await client.fetchQuery(folderChildrenQueryOptions(undefined))
    await client.fetchQuery(folderChildrenQueryOptions('folder-1'))

    expect(rootChildren.map((f) => f.id)).toEqual(['folder-1'])
    expect(seen[0]?.searchParams.get('page_size')).toBe('1000')
    expect(seen[0]?.searchParams.get('orderby')).toBe('name')
    expect(seen[0]?.searchParams.get('desc')).toBe('false')
    expect(seen[0]?.searchParams.get('parent_id')).toBeNull()
    expect(seen[1]?.searchParams.get('parent_id')).toBe('folder-1')
    expect(folderChildrenQueryOptions(undefined).queryKey).toEqual(fileKeys.folders(undefined))
    expect(folderChildrenQueryOptions('folder-1').queryKey).toEqual(fileKeys.folders('folder-1'))
  })
})
