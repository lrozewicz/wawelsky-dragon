/**
 * Spinacz akcji listy Plików (kontrakt WP E4-5c §7, T4): trzyma cele dialogów (zmiana nazwy,
 * przeniesienie, połączenie, usunięcie, podgląd, prześlij/nowy folder) i realizuje akcje wiersza
 * oraz zbiorcze. `FilesPage` zostaje przy siatce i toolbarze — logika, która nie zmieściłaby się
 * w limicie 300 linii, mieszka tutaj. Błędy meldujemy powiadomieniem `useNotifications`
 * (wzór `features/datasets/files/useFileActions.ts`).
 *
 * Akcje zbiorcze działają na zaznaczonych wierszach bieżącej strony. „Połącz” pomija foldery
 * (kontrakt §7 p. 2): gdy w zaznaczeniu są same foldery, przycisk jest nieaktywny i akcja nic nie
 * robi. Zaznaczenie czyścimy przy zamknięciu dialogów przenoszenia/łączenia/usuwania — dialogi
 * wołają `onClose` po sukcesie (i przy anulowaniu), a po udanej operacji zaznaczone wiersze
 * znikają z odświeżonej listy (kontrakt §7, wymagania T4 p. 3–4).
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../hooks/useNotifications/useNotifications'
import { errorText } from '../../lib/errorText'

import { downloadFile } from './downloadFile'
import type { FileAction } from './FileRowActions'
import { useDeleteFiles } from './mutations'
import type { FileItem } from './queries'

/** Żądanie dialogu z menu „Dodaj” (`null` = brak). */
export type FilesDialogRequest = 'upload' | 'folder' | null

export type FilesActionsParams = {
  /** Wiersze bieżącej strony — z nich bierzemy obiekty dla akcji zbiorczych. */
  rows: FileItem[]
  selectedIds: string[]
  /** Czyści zaznaczenie siatki (rodzic trzyma stan `selectedIds`). */
  onClearSelection: () => void
}

export type FilesActionsController = {
  dialog: FilesDialogRequest
  renameTarget: FileItem | null
  moveTargets: FileItem[] | null
  linkTargets: FileItem[] | null
  deleteTargets: FileItem[] | null
  previewDoc: { id: string; name: string } | null
  deleting: boolean
  selectedCount: number
  linkDisabled: boolean
  onAction: (action: FileAction, file: FileItem) => void
  openDialog: (dialog: Exclude<FilesDialogRequest, null>) => void
  closeDialog: () => void
  closeRename: () => void
  closeMove: () => void
  closeLink: () => void
  closeDelete: () => void
  closePreview: () => void
  linkSelected: () => void
  moveSelected: () => void
  deleteSelected: () => void
  confirmDelete: () => void
  clearSelection: () => void
}

export function useFilesActions(params: FilesActionsParams): FilesActionsController {
  const { rows, selectedIds, onClearSelection } = params
  const { t } = useTranslation()
  const { show } = useNotifications()
  const remove = useDeleteFiles()

  const [dialog, setDialog] = useState<FilesDialogRequest>(null)
  const [renameTarget, setRenameTarget] = useState<FileItem | null>(null)
  const [moveTargets, setMoveTargets] = useState<FileItem[] | null>(null)
  const [linkTargets, setLinkTargets] = useState<FileItem[] | null>(null)
  const [deleteTargets, setDeleteTargets] = useState<FileItem[] | null>(null)
  const [previewDoc, setPreviewDoc] = useState<{ id: string; name: string } | null>(null)

  const notifyError = (): void => {
    show(t('files.error.generic'), { severity: 'error' })
  }

  const selectedRows = rows.filter((row) => selectedIds.includes(row.id))
  // Kontrakt §7 p. 2: „Połącz” zbiorczo dotyczy tylko plików; foldery pomijamy.
  const linkableSelected = selectedRows.filter((row) => row.type !== 'folder')

  const onAction = (action: FileAction, file: FileItem): void => {
    if (action === 'rename') {
      setRenameTarget(file)
      return
    }
    if (action === 'move') {
      setMoveTargets([file])
      return
    }
    if (action === 'link') {
      setLinkTargets([file])
      return
    }
    if (action === 'delete') {
      setDeleteTargets([file])
      return
    }
    if (action === 'download') {
      void downloadFile(file).catch(notifyError)
      return
    }
    // preview: tylko pliki związane z dokumentem datasetu mają co pokazać (kontrakt §7 p. 5).
    const info = file.kbs_info[0]
    if (info !== undefined) {
      setPreviewDoc({ id: info.document_id, name: file.name })
    }
  }

  /** Zamknięcie dialogu operacji zbiorczej: cel znika, a zaznaczenie wracą do zera. */
  const closeBulkDialog = (reset: () => void): void => {
    reset()
    onClearSelection()
  }

  // Usunięcie: pełny sukces meldujemy zielono; kopertę częściową (kod 102) ostrzeżeniem z listą.
  const confirmDelete = (): void => {
    if (deleteTargets === null) return
    remove.mutate(
      { ids: deleteTargets.map((file) => file.id) },
      {
        onSuccess: (outcome) => {
          if (outcome.errors.length === 0) {
            show(t('files.delete.done'), { severity: 'success' })
            return
          }
          const partial = t('files.delete.partial', {
            ok: outcome.successCount,
            failed: outcome.errors.length,
          })
          show(`${partial} ${outcome.errors.join('; ')}`, { severity: 'warning' })
        },
        onError: (error) => {
          // Błąd koperty tłumaczony przy wyświetleniu (T5b); nieznany bez zmian, pusty → generyk.
          const text = errorText(error, t)
          show(text === '' ? t('files.error.generic') : text, {
            severity: 'error',
          })
        },
        onSettled: () => {
          setDeleteTargets(null)
          onClearSelection()
        },
      },
    )
  }

  return {
    dialog,
    renameTarget,
    moveTargets,
    linkTargets,
    deleteTargets,
    previewDoc,
    deleting: remove.isPending,
    selectedCount: selectedRows.length,
    linkDisabled: selectedRows.length > 0 && linkableSelected.length === 0,
    onAction,
    openDialog: (next) => setDialog(next),
    closeDialog: () => setDialog(null),
    closeRename: () => setRenameTarget(null),
    closeMove: () => closeBulkDialog(() => setMoveTargets(null)),
    closeLink: () => closeBulkDialog(() => setLinkTargets(null)),
    closeDelete: () => closeBulkDialog(() => setDeleteTargets(null)),
    closePreview: () => setPreviewDoc(null),
    linkSelected: () => {
      if (linkableSelected.length === 0) return
      setLinkTargets(linkableSelected)
    },
    moveSelected: () => {
      if (selectedRows.length === 0) return
      setMoveTargets(selectedRows)
    },
    deleteSelected: () => {
      if (selectedRows.length === 0) return
      setDeleteTargets(selectedRows)
    },
    confirmDelete,
    clearSelection: onClearSelection,
  }
}
