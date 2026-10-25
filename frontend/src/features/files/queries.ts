/**
 * Warstwa danych UI Plików (kontrakt WP E4-5c §1). Wzór: `features/datasets/files/queries.ts` —
 * jawne `queryOptions`, rozpakowanie koperty przez `apiCall`, klucze pod prefiksem `['files']`.
 * `ancestorsQueryOptions` odwraca kolejność z API (`[bieżący, …, root]`) na `[root, …, bieżący]`.
 */

import { keepPreviousData, queryOptions } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

export type FileItem = components['schemas']['FileItem']
export type FileParent = components['schemas']['FileParent']
export type FileKbInfo = components['schemas']['FileKbInfo']

/** Parametry listy plików: `parentId: undefined` = root, `keywords: ''` = brak filtra. */
export type FilesQuery = {
  parentId: string | undefined
  keywords: string
  page: number
  pageSize: number
  orderby: 'create_time' | 'name' | 'size'
  desc: boolean
}

export const DEFAULT_FILES_QUERY: FilesQuery = {
  parentId: undefined,
  keywords: '',
  page: 1,
  pageSize: 15,
  orderby: 'create_time',
  desc: true,
}

export const fileKeys = {
  all: ['files'] as const,
  list: (q: FilesQuery) => ['files', 'list', q] as const,
  ancestors: (id: string) => ['files', 'ancestors', id] as const,
  folders: (parentId: string | undefined) => ['files', 'folders', parentId ?? 'root'] as const,
}

/** `''` nie trafia do zapytania (openapi-fetch pomija `undefined`). */
const blankToUndefined = (value: string): string | undefined => (value === '' ? undefined : value)

export function filesListQueryOptions(q: FilesQuery) {
  return queryOptions({
    queryKey: fileKeys.list(q),
    queryFn: async () => {
      const data = await apiCall<components['schemas']['FileList']>(
        api.GET('/api/v1/files', {
          params: {
            query: {
              parent_id: q.parentId,
              keywords: blankToUndefined(q.keywords),
              page: q.page,
              page_size: q.pageSize,
              orderby: q.orderby,
              desc: q.desc,
            },
          },
        }),
      )
      return { files: data.files, total: data.total, parentFolder: data.parent_folder }
    },
    // Paginacja bez migotania: poprzednia strona zostaje w cache, gdy leci nowa.
    placeholderData: keepPreviousData,
  })
}

export function ancestorsQueryOptions(folderId: string | undefined) {
  return queryOptions({
    queryKey: fileKeys.ancestors(folderId ?? 'root'),
    // Brak folderu (root) → API nie jest pytane (kontrakt §1).
    enabled: folderId !== undefined,
    queryFn: async () => {
      // `enabled` gwarantuje, że identyfikator jest znany.
      const data = await apiCall<components['schemas']['FileAncestors']>(
        api.GET('/api/v1/files/{file_id}/ancestors', {
          params: { path: { file_id: folderId as string } },
        }),
      )
      return [...data.parent_folders].reverse()
    },
  })
}

export function folderChildrenQueryOptions(parentId: string | undefined) {
  return queryOptions({
    queryKey: fileKeys.folders(parentId),
    queryFn: async () => {
      const data = await apiCall<components['schemas']['FileList']>(
        api.GET('/api/v1/files', {
          params: {
            query: { parent_id: parentId, page_size: 1000, orderby: 'name', desc: false },
          },
        }),
      )
      return data.files.filter((file) => file.type === 'folder')
    },
  })
}
