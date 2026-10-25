/**
 * Stan i akcje panelu chunków (kontrakt WP E3-H2a §K3). Wydzielone z `ChunksPanel.tsx`,
 * żeby widok zmieścił się w limicie 300 linii (DEC-098). Trzyma stronę listy, szukanie, filtr
 * dostępności (serwerowy — `available` w zapytaniu, E3-H2a zastępuje DEC-141), zaznaczenie, cel
 * dialogu i potwierdzenie usunięcia; mutacje woła gotowe hooki z `mutations.ts` (T1).
 *
 * PATCH edycji budujemy z różnicy wobec oryginału: `available` jedzie jako 0/1, a brak różnic
 * kończy się zamknięciem dialogu bez żądania (kontrakt §Wymagania p. 3).
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { useCreateChunk, useDeleteChunks, useSwitchChunks, useUpdateChunk } from './mutations'
import type { ChunkPatch } from './mutations'
import { CHUNKS_PAGE_SIZE, chunksListQueryOptions } from './queries'
import type { Chunk, ChunkDoc, ChunksFilter } from './queries'
import type { ChunkFormValues } from './chunkSchema'

/** Cel otwartego dialogu chunku: `'new'` = tryb nowego, `null` = zamknięty. */
export type ChunksEditTarget = Chunk | 'new' | null

export type ChunksPanelStateArgs = {
  datasetId: string
  docId: string
  onDocLoaded?: (doc: ChunkDoc) => void
}

/** Porównanie list tekstów po wartościach — `important_keywords` i `questions` z formularza. */
function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

/** Łatka tylko z polami różniącymi się od oryginału; `null`, gdy formularz nic nie zmienił. */
function buildPatch(original: Chunk, values: ChunkFormValues): ChunkPatch | null {
  const patch: ChunkPatch = {}
  if (values.content !== original.content) patch.content = values.content
  if (!sameList(values.important_keywords, original.important_keywords)) {
    patch.important_keywords = values.important_keywords
  }
  if (!sameList(values.questions, original.questions)) patch.questions = values.questions
  if (values.available !== original.available) patch.available = values.available ? 1 : 0
  return Object.keys(patch).length === 0 ? null : patch
}

export function useChunksPanelState(args: ChunksPanelStateArgs) {
  const { datasetId, docId, onDocLoaded } = args

  const [page, setPage] = useState(1)
  const [keywords, setKeywords] = useState('')
  const [filter, setFilter] = useState<ChunksFilter>('all')
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [activeId, setActiveId] = useState<string | null>(null)
  const [editing, setEditing] = useState<ChunksEditTarget>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [saveError, setSaveError] = useState(false)
  const [deleteError, setDeleteError] = useState(false)

  const query = useQuery(
    chunksListQueryOptions(datasetId, docId, {
      page,
      pageSize: CHUNKS_PAGE_SIZE,
      keywords,
      available: filter,
    }),
  )

  const switchChunks = useSwitchChunks(datasetId, docId)
  const deleteChunks = useDeleteChunks(datasetId, docId)
  const createChunk = useCreateChunk(datasetId, docId)
  const updateChunk = useUpdateChunk(datasetId, docId)

  const doc = query.data?.doc
  const total = query.data?.total ?? 0

  // Nazwa dokumentu dla breadcrumbów — rodzic dostaje ją razem z listą (kontrakt §ChunksPanelProps).
  useEffect(() => {
    if (doc !== undefined) onDocLoaded?.(doc)
  }, [doc, onDocLoaded])

  // Filtr dostępności i strona jadą na serwer (E3-H2a §K3) — bez filtra klienckiego.
  const chunks = query.data?.chunks ?? []

  const filtered = filter !== 'all' || keywords !== ''
  const pageCount = Math.ceil(total / CHUNKS_PAGE_SIZE)
  const selectedCount = selected.size
  const allOnPageSelected = chunks.length > 0 && chunks.every((chunk) => selected.has(chunk.id))

  function clearSelection(): void {
    setSelected(new Set())
  }

  function handleKeywordsChange(next: string): void {
    setKeywords(next)
    setPage(1)
    clearSelection()
  }

  function handleFilterChange(next: ChunksFilter): void {
    setFilter(next)
    setPage(1)
    clearSelection()
  }

  function toggleSelect(id: string): void {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  /** „Zaznacz stronę” / odznacz — zbiór chunków widocznych po filtrze serwerowym. */
  function togglePage(): void {
    setSelected((previous) => {
      const next = new Set(previous)
      for (const chunk of chunks) {
        if (allOnPageSelected) next.delete(chunk.id)
        else next.add(chunk.id)
      }
      return next
    })
  }

  function toggleAvailable(id: string, available: boolean): void {
    switchChunks.mutate({ ids: [id], available })
  }

  function activate(chunk: Chunk): void {
    setActiveId(chunk.id)
  }

  function setAvailableForSelection(available: boolean): void {
    switchChunks.mutate({ ids: [...selected], available })
  }

  function closeDialog(): void {
    setEditing(null)
    setSaveError(false)
  }

  function submit(values: ChunkFormValues): void {
    setSaveError(false)
    if (editing === 'new') {
      createChunk.mutate(
        {
          content: values.content,
          important_keywords: values.important_keywords,
          questions: values.questions,
        },
        { onSuccess: closeDialog, onError: () => setSaveError(true) },
      )
      return
    }
    if (editing === null) return
    const patch = buildPatch(editing, values)
    if (patch === null) {
      closeDialog()
      return
    }
    updateChunk.mutate(
      { id: editing.id, patch },
      { onSuccess: closeDialog, onError: () => setSaveError(true) },
    )
  }

  function confirmDelete(): void {
    deleteChunks.mutate(
      { ids: [...selected] },
      {
        onSuccess: () => {
          clearSelection()
          setDeleteOpen(false)
          setDeleteError(false)
        },
        // Dialog zamykamy też przy błędzie — inaczej Alert z `deleteError` zostałby pod nim ukryty.
        onError: () => {
          setDeleteError(true)
          setDeleteOpen(false)
        },
      },
    )
  }

  return {
    chunks,
    total,
    isPending: query.isPending,
    isError: query.isError,
    /** Ponowienie zapytania o listę chunków (przycisk w `QueryError`). */
    refetch: () => void query.refetch(),
    filtered,
    page,
    pageCount,
    keywords,
    filter,
    expanded,
    selected,
    selectedCount,
    allOnPageSelected,
    activeId,
    editing,
    deleteOpen,
    saving: createChunk.isPending || updateChunk.isPending,
    deleting: deleteChunks.isPending,
    saveError,
    deleteError,
    setPage,
    handleKeywordsChange,
    handleFilterChange,
    setExpanded,
    toggleSelect,
    togglePage,
    toggleAvailable,
    activate,
    setAvailableForSelection,
    openAdd: () => {
      setEditing('new')
    },
    openEdit: (chunk: Chunk) => {
      setEditing(chunk)
    },
    closeDialog,
    submit,
    openDelete: () => {
      setDeleteError(false)
      setDeleteOpen(true)
    },
    closeDelete: () => {
      setDeleteOpen(false)
    },
    confirmDelete,
  }
}
