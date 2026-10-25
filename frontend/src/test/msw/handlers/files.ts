import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'
import {
  FILES_ROOT_ID,
  ancestorChain,
  childrenOf,
  deleteRows,
  descendantIds,
  findRow,
  insertFolder,
  insertUpload,
  isFolder,
  linkFiles,
  moveFiles,
  parentFolder,
  presentCreated,
  presentItem,
  presentParent,
  resolveParent,
  sortRows,
} from './filesData'
import type { FileList } from './filesData'

export { filesFixtureItems, filesFixtureRoot, resetFilesFixtures } from './filesData'
export type { FileCreated, FileItem, FileKbInfo, FileParent } from './filesData'

function intParam(value: string | null, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

// Jak backend (§D5): brak `desc` → true, a tylko „false" (bez wielkości liter) daje false.
function boolParam(value: string | null): boolean {
  return value === null ? true : value.toLowerCase() !== 'false'
}

function dataError(message: string): Response {
  return HttpResponse.json({ code: 102, message })
}

/**
 * Handlery menedżera plików (kontrakt WP E4-5c §5): listing, tworzenie folderu/upload, `move`,
 * `delete`, `link-to-datasets`, `parent`, `ancestors` i pobranie treści. Stan trzyma `filesData.ts`.
 */
export function filesHandlers(): HttpHandler[] {
  return [
    http.get(apiUrl('/api/v1/files'), ({ request }) => {
      const url = new URL(request.url)
      const parentId = url.searchParams.get('parent_id')
      const listed = parentId === null ? findRow(FILES_ROOT_ID) : findRow(parentId)
      if (listed === undefined || !isFolder(listed)) return dataError('Folder not found!')
      const context = findRow(listed.parent_id) ?? listed
      const keywords = url.searchParams.get('keywords')
      const matched =
        keywords === null || keywords === ''
          ? childrenOf(listed.id)
          : descendantIds(listed.id)
              .flatMap((id) => findRow(id) ?? [])
              .filter((row) => row.name.toLowerCase().includes(keywords.toLowerCase()))
      const ordered = sortRows(
        matched,
        url.searchParams.get('orderby'),
        boolParam(url.searchParams.get('desc')),
      )
      const page = intParam(url.searchParams.get('page'), 1)
      const pageSize = intParam(url.searchParams.get('page_size'), 15)
      const from = (page - 1) * pageSize
      const data: FileList = {
        files: ordered.slice(from, from + pageSize).map((row) => presentItem(row)),
        parent_folder: presentParent(context),
        total: matched.length,
      }
      return HttpResponse.json({ code: 0, message: '', data })
    }),

    http.post(apiUrl('/api/v1/files'), async ({ request }) => {
      const contentType = request.headers.get('content-type') ?? ''
      if (contentType.includes('multipart/form-data')) {
        const form = await request.formData()
        // `File` z `formData()` MSW nie jest `instanceof File` jsdomu — rozpoznajemy po typie.
        const uploaded = form
          .getAll('file')
          .filter((entry): entry is File => typeof entry !== 'string')
        if (uploaded.length === 0) return HttpResponse.json({ code: 101, message: 'No file part!' })
        const rawParent = form.get('parent_id')
        const parent = resolveParent(typeof rawParent === 'string' ? rawParent : undefined)
        if (parent === null) return dataError('Parent folder not found!')
        const created = uploaded.map((file) => insertUpload(parent.id, file.name, file.size))
        return HttpResponse.json({ code: 0, message: '', data: created.map(presentCreated) })
      }
      const body = (await request.json()) as { name?: string; parent_id?: string | null }
      const parent = resolveParent(body.parent_id)
      if (parent === null) return dataError('Parent folder not found!')
      return HttpResponse.json({
        code: 0,
        message: '',
        data: presentCreated(insertFolder(parent.id, body.name ?? '')),
      })
    }),

    http.post(apiUrl('/api/v1/files/move'), async ({ request }) => {
      const body = (await request.json()) as {
        src_file_ids?: string[]
        dest_file_id?: string | null
        new_name?: string | null
      }
      const result = moveFiles(
        body.src_file_ids ?? [],
        body.dest_file_id ?? null,
        body.new_name ?? null,
      )
      return result.ok
        ? HttpResponse.json({ code: 0, message: '', data: true })
        : dataError(result.message)
    }),

    http.post(apiUrl('/api/v1/files/link-to-datasets'), async ({ request }) => {
      const url = new URL(request.url)
      const append = (url.searchParams.get('mode') ?? 'replace').toLowerCase() === 'add'
      const body = (await request.json()) as { file_ids?: string[]; kb_ids?: string[] }
      const result = linkFiles(body.file_ids ?? [], body.kb_ids ?? [], append)
      return result.ok
        ? HttpResponse.json({ code: 0, message: '', data: true })
        : dataError(result.message)
    }),

    http.delete(apiUrl('/api/v1/files'), async ({ request }) => {
      const body = (await request.json()) as { ids?: string[] }
      const { successCount, errors } = deleteRows(body.ids ?? [])
      if (errors.length > 0) {
        return HttpResponse.json({
          code: 102,
          message: `Deleted files failed with ${errors.length} errors`,
          data: { success_count: successCount, errors },
        })
      }
      return HttpResponse.json({ code: 0, message: '', data: { success_count: successCount } })
    }),

    http.get(apiUrl('/api/v1/files/:fileId/parent'), ({ params }) => {
      const parent = parentFolder(String(params.fileId))
      if (parent === null) return dataError('Folder not found!')
      return HttpResponse.json({ code: 0, message: '', data: { parent_folder: parent } })
    }),

    http.get(apiUrl('/api/v1/files/:fileId/ancestors'), ({ params }) => {
      const chain = ancestorChain(String(params.fileId))
      if (chain === null) return dataError('Folder not found!')
      return HttpResponse.json({ code: 0, message: '', data: { parent_folders: chain } })
    }),

    http.get(apiUrl('/api/v1/files/:fileId'), ({ params }) => {
      const row = findRow(String(params.fileId))
      if (row === undefined) return dataError('document not found')
      if (isFolder(row)) return dataError('This file is empty.')
      return new HttpResponse(`treść ${row.name}`, {
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Content-Disposition': `attachment; filename="${row.name}"`,
        },
      })
    }),
  ]
}
