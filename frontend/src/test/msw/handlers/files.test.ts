import { beforeEach, describe, expect, it } from 'vitest'

import { server } from '../server'

import { apiUrl } from './common'
import { filesFixtureItems, filesFixtureRoot, filesHandlers, resetFilesFixtures } from './files'

type KbInfo = { kb_id: string; kb_name: string; document_id: string }
type FileRow = { id: string; name: string; parent_id: string; size: number; kbs_info: KbInfo[] }
type FilesData = { files: FileRow[]; parent_folder: { id: string }; total: number }
type Envelope<T = unknown> = { code: number; message: string; data: T }

// Każde żądanie dostaje świeży zestaw tras nad wspólnym magazynem modułu (wzór `retrieval.test.ts`).
function mountFiles(): void {
  server.use(...filesHandlers())
}

async function getFiles(query = ''): Promise<Envelope<FilesData>> {
  mountFiles()
  const response = await fetch(apiUrl('/api/v1/files' + query))
  return (await response.json()) as Envelope<FilesData>
}

async function getJson<T>(path: string): Promise<Envelope<T>> {
  mountFiles()
  const response = await fetch(apiUrl(path))
  return (await response.json()) as Envelope<T>
}

async function postJson<T = unknown>(path: string, body: unknown): Promise<Envelope<T>> {
  mountFiles()
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as Envelope<T>
}

function names(response: Envelope<FilesData>): string[] {
  return response.data.files.map((file) => file.name)
}

beforeEach(() => {
  resetFilesFixtures()
})

describe('handlery MSW — /files (kontrakt WP E4-5c §5)', () => {
  it('ziarno: root-1 i folder-1 z has_child_folder', () => {
    expect(filesFixtureRoot.id).toBe('root-1')

    const folder = filesFixtureItems.find((item) => item.id === 'folder-1')
    expect(folder?.type).toBe('folder')
    expect(folder?.has_child_folder).toBe(true)
    expect(filesFixtureItems.map((item) => item.id)).toEqual([
      'folder-1',
      'file-1',
      'file-2',
      'file-3',
    ])
  })

  it('GET /files bez parent_id zwraca root malejąco po create_time', async () => {
    const response = await getFiles()

    expect(response.code).toBe(0)
    expect(response.data.total).toBe(3)
    expect(response.data.parent_folder.id).toBe('root-1')
    expect(names(response)).toEqual(['Projekty', 'notatki.txt', 'raport.pdf'])
  })

  it('GET /files?parent_id=folder-1 zwraca umowę', async () => {
    const response = await getFiles('?parent_id=folder-1')

    expect(response.data.total).toBe(1)
    expect(names(response)).toEqual(['umowa.docx'])
  })

  it('GET /files?keywords filtruje bez wielkości liter', async () => {
    const response = await getFiles('?keywords=RAP')

    expect(response.data.total).toBe(1)
    expect(names(response)).toEqual(['raport.pdf'])
  })

  it('GET /files paginuje, a total liczy przed paginacją', async () => {
    const response = await getFiles('?orderby=name&desc=false&page=2&page_size=2')

    expect(response.data.total).toBe(3)
    expect(names(response)).toEqual(['raport.pdf'])
  })

  it('GET /files?parent_id=nienany zwraca kopertę 102', async () => {
    const response = await getFiles('?parent_id=nie-ma')

    expect(response.code).toBe(102)
    expect(response.message).toBe('Folder not found!')
  })

  it('POST /files JSON tworzy folder widoczny w kolejnym listingu', async () => {
    const created = await postJson<FileRow>('/api/v1/files', {
      name: 'Nowy',
      type: 'folder',
      parent_id: 'root-1',
    })

    expect(created.code).toBe(0)
    expect(created.data.name).toBe('Nowy')
    expect(created.data.parent_id).toBe('root-1')

    const response = await getFiles()
    expect(response.data.total).toBe(4)
    expect(names(response)).toContain('Nowy')
  })

  it('POST /files JSON z nieznanym parent_id zwraca 102', async () => {
    const response = await postJson('/api/v1/files', {
      name: 'Nowy',
      type: 'folder',
      parent_id: 'x',
    })

    expect(response.code).toBe(102)
    expect(response.message).toBe('Parent folder not found!')
  })

  it('POST /files multipart zmienia nazwę przy kolizji', async () => {
    mountFiles()
    // Ciało multipart budujemy ręcznie: jsdomowy `FormData` nie przechodzi przez przechwytywacz
    // MSW (błąd `_buffer`), a `request.formData()` w handlerze i tak parsuje surowe bajty.
    const boundary = '----wd-files-test'
    const body =
      `--${boundary}\r\n` +
      'Content-Disposition: form-data; name="file"; filename="notatki.txt"\r\n' +
      'Content-Type: text/plain\r\n\r\n' +
      'tresc\r\n' +
      `--${boundary}--\r\n`
    const response = await fetch(apiUrl('/api/v1/files'), {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body,
    })
    const envelope = (await response.json()) as Envelope<FileRow[]>

    expect(envelope.code).toBe(0)
    expect(envelope.data).toHaveLength(1)
    expect(envelope.data[0]?.name).toBe('notatki(1).txt')
    expect(envelope.data[0]?.parent_id).toBe('root-1')
    expect(envelope.data[0]?.size).toBe(5)
  })

  it('POST /files/move z new_name zmienia nazwę pliku', async () => {
    const moved = await postJson('/api/v1/files/move', {
      src_file_ids: ['file-1'],
      new_name: 'inna.txt',
    })

    expect(moved.code).toBe(0)
    expect(moved.data).toBe(true)
    expect(names(await getFiles())).toContain('inna.txt')
  })

  it('POST /files/move folderu do samego siebie zwraca 102', async () => {
    const response = await postJson('/api/v1/files/move', {
      src_file_ids: ['folder-1'],
      dest_file_id: 'folder-1',
    })

    expect(response.code).toBe(102)
    expect(response.message).toBe('Cannot move folder to its subfolder')
  })

  it('DELETE /files usuwa poprawne id i raportuje brakujące', async () => {
    mountFiles()
    const response = await fetch(apiUrl('/api/v1/files'), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ['file-1', 'nie-ma'] }),
    })
    const body = (await response.json()) as Envelope<{ success_count: number; errors: string[] }>

    expect(body.code).toBe(102)
    expect(body.data.success_count).toBe(1)
    expect(body.data.errors).toEqual(['File or Folder not found: nie-ma'])
  })

  it('POST /files/link-to-datasets podmienia kbs_info', async () => {
    const linked = await postJson('/api/v1/files/link-to-datasets', {
      file_ids: ['file-1'],
      kb_ids: ['ds-1'],
    })

    expect(linked.code).toBe(0)
    expect(linked.data).toBe(true)

    const response = await getFiles()
    const row = response.data.files.find((file) => file.id === 'file-1')
    expect(row?.kbs_info).toEqual([
      { kb_id: 'ds-1', kb_name: 'Baza wiedzy', document_id: 'doc-file-1-ds-1' },
    ])
  })

  it('POST /files/link-to-datasets?mode=add dopisuje wpisy', async () => {
    await postJson('/api/v1/files/link-to-datasets?mode=add', {
      file_ids: ['file-1'],
      kb_ids: ['ds-2'],
    })

    const response = await getFiles()
    const row = response.data.files.find((file) => file.id === 'file-1')
    expect(row?.kbs_info.map((info) => info.kb_id)).toEqual(['ds-2'])
  })

  it('GET /files/file-1/ancestors zwraca [bieżący, root]', async () => {
    const response = await getJson<{ parent_folders: { id: string }[] }>(
      '/api/v1/files/file-1/ancestors',
    )

    expect(response.code).toBe(0)
    expect(response.data.parent_folders.map((folder) => folder.id)).toEqual(['file-1', 'root-1'])
  })

  it('GET /files/:id pobiera treść pliku z nagłówkami', async () => {
    mountFiles()
    const response = await fetch(apiUrl('/api/v1/files/file-1'))

    expect(response.status).toBe(200)
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8')
    expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="notatki.txt"')
    expect(await response.text()).toBe('treść notatki.txt')
  })

  it('GET /files/:id/parent zwraca folder nadrzędny', async () => {
    const response = await getJson<{ parent_folder: { id: string } }>('/api/v1/files/file-3/parent')

    expect(response.code).toBe(0)
    expect(response.data.parent_folder.id).toBe('folder-1')
  })
})
