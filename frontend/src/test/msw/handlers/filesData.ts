import type { components } from '../../../api/schema.gen'

import { fixtureChatDatasets } from './datasets'

// Kształty z `schema.gen.ts` (kontrakt WP E4-5c §5) — importujemy typy, nie kopiujemy pól.
export type FileItem = components['schemas']['FileItem']
export type FileParent = components['schemas']['FileParent']
export type FileCreated = components['schemas']['FileCreated']
export type FileKbInfo = components['schemas']['FileKbInfo']
export type FileList = components['schemas']['FileList']

export const FILES_ROOT_ID = 'root-1'

const FOLDER = 'folder'
const DATE = '2025-01-01 00:00:00'

// Nazwy datasetów do `kbs_info` i `link-to-datasets` bierzemy z fixture'ów datasetów (§5).
const KB_NAMES = new Map(fixtureChatDatasets.map((dataset) => [dataset.id, dataset.name]))

/** Typ wiersza z rozszerzenia — skrót `filename_type` backendu (poza pdf/visual/aural zostaje `doc`). */
function fileType(name: string): string {
  const lower = name.toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (/\.(png|jpe?g|gif|bmp|webp|svg|mp4|mov|avi|mkv)$/.test(lower)) return 'visual'
  if (/\.(wav|mp3|aac|ogg|flac)$/.test(lower)) return 'aural'
  return 'doc'
}

type RowSpec = {
  id: string
  name: string
  parentId: string
  createTime: number
  size?: number
  type?: string
  kbsInfo?: FileKbInfo[]
}

function makeRow(spec: RowSpec): FileItem {
  const type = spec.type ?? fileType(spec.name)
  return {
    id: spec.id,
    tenant_id: 'tenant-1',
    created_by: 'user-1',
    parent_id: spec.parentId,
    name: spec.name,
    type,
    size: spec.size ?? 0,
    location: type === FOLDER ? '' : spec.name,
    source_type: '',
    create_time: spec.createTime,
    create_date: DATE,
    update_time: spec.createTime,
    update_date: DATE,
    kbs_info: spec.kbsInfo ?? [],
    has_child_folder: null,
  }
}

function rootRow(): FileItem {
  return makeRow({
    id: FILES_ROOT_ID,
    name: 'Pliki',
    parentId: FILES_ROOT_ID,
    type: FOLDER,
    createTime: 1_000_000_000_000,
  })
}

// Ziarno kontraktu §5: root z `Projekty`/`notatki.txt`/`raport.pdf`; `umowa.docx` w `Projekty`.
// Czasy tak dobrane, by domyślne `create_time` malejąco dawało Projekty, notatki.txt, raport.pdf.
function seedRows(): FileItem[] {
  return [
    rootRow(),
    makeRow({
      id: 'folder-1',
      name: 'Projekty',
      parentId: FILES_ROOT_ID,
      type: FOLDER,
      createTime: 1_700_000_000_003,
    }),
    makeRow({
      id: 'file-1',
      name: 'notatki.txt',
      parentId: FILES_ROOT_ID,
      createTime: 1_700_000_000_002,
      size: 1234,
    }),
    makeRow({
      id: 'file-2',
      name: 'raport.pdf',
      parentId: FILES_ROOT_ID,
      createTime: 1_700_000_000_001,
      size: 2048,
      kbsInfo: [{ kb_id: 'ds-1', kb_name: KB_NAMES.get('ds-1') ?? '', document_id: 'doc-1' }],
    }),
    makeRow({
      id: 'file-3',
      name: 'umowa.docx',
      parentId: 'folder-1',
      createTime: 1_700_000_000_004,
      size: 512,
    }),
  ]
}

// Stan w pamięci modułu (wzór `searches.ts`): każde `filesHandlers()` dzieli ten sam magazyn,
// a `resetFilesFixtures()` wraca do ziarna.
let rows: FileItem[] = seedRows()
let nextId = 4
let nextTime = 1_700_000_100_000

/** Przywraca magazyn do ziarna kontraktu §5. */
export function resetFilesFixtures(): void {
  rows = seedRows()
  nextId = 4
  nextTime = 1_700_000_100_000
}

export function isFolder(row: FileItem): boolean {
  return row.type === FOLDER
}

function hasChild(all: FileItem[], folderId: string): boolean {
  // Liczone ze stanu (§5): `Projekty` ma dziecko `umowa.docx`, więc `has_child_folder` = true.
  return all.some((row) => row.parent_id === folderId && row.id !== folderId)
}

export function findRow(id: string): FileItem | undefined {
  return rows.find((row) => row.id === id)
}

export function presentItem(row: FileItem): FileItem {
  return {
    ...row,
    kbs_info: row.kbs_info.map((info) => ({ ...info })),
    has_child_folder: isFolder(row) ? hasChild(rows, row.id) : null,
  }
}

export function presentParent(row: FileItem): FileParent {
  return {
    id: row.id,
    tenant_id: row.tenant_id,
    created_by: row.created_by,
    parent_id: row.parent_id,
    name: row.name,
    type: row.type,
    size: row.size,
    location: row.location,
    source_type: row.source_type,
    create_time: row.create_time,
    create_date: row.create_date,
    update_time: row.update_time,
    update_date: row.update_date,
  }
}

export function presentCreated(row: FileItem): FileCreated {
  return {
    id: row.id,
    tenant_id: row.tenant_id,
    created_by: row.created_by,
    parent_id: row.parent_id,
    name: row.name,
    type: row.type,
    size: row.size,
    location: row.location,
    source_type: row.source_type,
  }
}

function fixtureItems(): FileItem[] {
  const all = seedRows()
  return all
    .filter((row) => row.id !== FILES_ROOT_ID)
    .map((row) => ({ ...row, has_child_folder: hasChild(all, row.id) }))
}

export const filesFixtureRoot: FileParent = presentParent(rootRow())
export const filesFixtureItems: FileItem[] = fixtureItems()

export function childrenOf(parentId: string): FileItem[] {
  return rows.filter((row) => row.parent_id === parentId && row.id !== parentId)
}

export function descendantIds(parentId: string): string[] {
  const ids: string[] = []
  const queue = childrenOf(parentId)
  while (queue.length > 0) {
    const row = queue.shift()
    if (row === undefined) break
    ids.push(row.id)
    queue.push(...childrenOf(row.id))
  }
  return ids
}

export function isSelfOrDescendant(node: FileItem, ancestorId: string): boolean {
  const seen = new Set<string>()
  let current: FileItem | undefined = node
  while (current !== undefined && !seen.has(current.id)) {
    if (current.id === ancestorId) return true
    seen.add(current.id)
    current = findRow(current.parent_id)
  }
  return false
}

function compare(a: FileItem, b: FileItem, field: 'create_time' | 'name' | 'size'): number {
  if (field === 'name') return a.name < b.name ? -1 : a.name > b.name ? 1 : 0
  const left = field === 'size' ? a.size : a.create_time
  const right = field === 'size' ? b.size : b.create_time
  return left < right ? -1 : left > right ? 1 : 0
}

export function sortRows(list: FileItem[], orderby: string | null, desc: boolean): FileItem[] {
  const field = orderby === 'name' || orderby === 'size' ? orderby : 'create_time'
  const direction = desc ? -1 : 1
  return [...list].sort((a, b) => {
    const byField = compare(a, b, field)
    if (byField !== 0) return byField * direction
    const byId = a.id < b.id ? -1 : a.id > b.id ? 1 : 0
    return byId * direction
  })
}

function uniqueName(parentId: string, name: string): string {
  const taken = (candidate: string): boolean =>
    rows.some((row) => row.parent_id === parentId && row.name === candidate)
  if (!taken(name)) return name
  const dot = name.lastIndexOf('.')
  const base = dot > 0 ? name.slice(0, dot) : name
  const ext = dot > 0 ? name.slice(dot) : ''
  let index = 1
  while (taken(`${base}(${index})${ext}`)) index += 1
  return `${base}(${index})${ext}`
}

function insertRow(parentId: string, name: string, size: number, type: string): FileItem {
  const row = makeRow({ id: `file-${nextId}`, name, parentId, size, type, createTime: nextTime })
  nextId += 1
  nextTime += 1
  rows.push(row)
  return row
}

export function insertFolder(parentId: string, name: string): FileItem {
  return insertRow(parentId, name, 0, FOLDER)
}

export function insertUpload(parentId: string, name: string, size: number): FileItem {
  return insertRow(parentId, uniqueName(parentId, name), size, fileType(name))
}

export function resolveParent(parentId: string | null | undefined): FileItem | null {
  if (parentId === null || parentId === undefined || parentId === '') return rootRow()
  const row = findRow(parentId)
  return row !== undefined && isFolder(row) ? row : null
}

export function deleteRows(ids: string[]): { successCount: number; errors: string[] } {
  const errors: string[] = []
  let successCount = 0
  for (const id of ids) {
    const row = findRow(id)
    if (row === undefined) {
      errors.push(`File or Folder not found: ${id}`)
      continue
    }
    const removed = new Set([row.id, ...descendantIds(row.id)])
    rows = rows.filter((item) => !removed.has(item.id))
    successCount += removed.size
  }
  return { successCount, errors }
}

type OpResult = { ok: true } | { ok: false; message: string }

export function moveFiles(
  srcIds: string[],
  destId: string | null,
  newName: string | null,
): OpResult {
  const sources: FileItem[] = []
  for (const id of srcIds) {
    const row = findRow(id)
    if (row === undefined) return { ok: false, message: 'Source files not found!' }
    sources.push(row)
  }
  let dest: FileItem | undefined
  if (destId !== null && destId !== '') {
    const found = findRow(destId)
    if (found === undefined || !isFolder(found)) {
      return { ok: false, message: 'Parent folder not found!' }
    }
    if (sources.some((row) => isSelfOrDescendant(found, row.id))) {
      return { ok: false, message: 'Cannot move folder to its subfolder' }
    }
    dest = found
  }
  if (newName !== null && newName !== '') {
    for (const row of sources) {
      row.name = newName
      row.location = newName
    }
  }
  if (dest !== undefined) {
    for (const row of sources) row.parent_id = dest.id
  }
  return { ok: true }
}

export function linkFiles(fileIds: string[], kbIds: string[], append: boolean): OpResult {
  const targets: FileItem[] = []
  for (const id of fileIds) {
    const row = findRow(id)
    if (row === undefined) return { ok: false, message: 'File not found!' }
    targets.push(row)
  }
  for (const kbId of kbIds) {
    if (!KB_NAMES.has(kbId)) return { ok: false, message: 'Dataset not found' }
  }
  for (const row of targets) {
    const links: FileKbInfo[] = kbIds.map((kbId) => ({
      kb_id: kbId,
      kb_name: KB_NAMES.get(kbId) ?? '',
      document_id: `doc-${row.id}-${kbId}`,
    }))
    row.kbs_info = append ? [...row.kbs_info, ...links] : links
  }
  return { ok: true }
}

export function parentFolder(id: string): FileParent | null {
  const row = findRow(id)
  if (row === undefined) return null
  const parent = findRow(row.parent_id)
  return parent === undefined ? null : presentParent(parent)
}

export function ancestorChain(id: string): FileParent[] | null {
  const row = findRow(id)
  if (row === undefined) return null
  // Kolejność API: [bieżący, rodzic, …, root] — `ancestorsQueryOptions` odwraca ją dla UI.
  const chain: FileParent[] = []
  const seen = new Set<string>()
  let current: FileItem | undefined = row
  while (current !== undefined && !seen.has(current.id)) {
    chain.push(presentParent(current))
    seen.add(current.id)
    current = current.parent_id === current.id ? undefined : findRow(current.parent_id)
  }
  return chain
}
