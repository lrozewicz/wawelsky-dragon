/**
 * Spinacz akcji zakładki Pliki (kontrakt WP E3-3b §T7): stan dialogów (zmiana nazwy, metoda
 * chunkowania, ponowne parsowanie, potwierdzenie usunięcia) i handlery mutacji. `DatasetFilesTab`
 * zostaje przy siatce i toolbarze — logika, która nie zmieściłaby się w limicie 300 linii, mieszka
 * tutaj. Błędy mutacji i pobrania meldujemy powiadomieniem `useNotifications` treścią
 * z `mutationMessage` (T3b: komunikat serwera wg INVENTORY; generyk = `…error.generic`);
 * sukces zmiany nazwy dokumentu — toastem `files.toast.renamed` (kontrakt WP E3-7 §C3/T1).
 * Zaznaczenia NIE czyścimy po akcji zbiorczej (kontrakt WP E3-H2a §K6): wiersze, które zostały na
 * liście, zostają zaznaczone, a id nieobecnych wypadają przy odświeżeniu listy.
 * Od WP E6-1b T5a także pozycje menu ⋮ (`rowMenuItems` — z „Metadane”, kontrakt WP E6-1b §4),
 * bo przeniesienie ich z `DatasetFilesTab` utrzymuje go w limicie 300 linii.
 */

import { useState } from 'react'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import LabelOutlinedIcon from '@mui/icons-material/LabelOutlined'
import { useTranslation } from 'react-i18next'

import type { RowActionItem } from '../../../components/RowActionsMenu'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { downloadDocument } from '../../../lib/download'
import { mutationMessage } from '../config/helpers'
import type { ChunkMethodDialogProps } from './ChunkMethodDialog'
import type { MetadataDrawerProps } from './MetadataDrawer'
import {
  useBatchUpdateStatus,
  useDeleteDocuments,
  useParseDocuments,
  useStopDocuments,
  useUpdateDocument,
} from './mutations'
import { canDelete, hasChunks } from './parsingState'
import type { RenameDocumentDialogProps } from './RenameDocumentDialog'
import type { ReparseDialogProps } from './ReparseDialog'
import type { DocumentRow } from './queries'

/** Dialogi sterowane z jednego miejsca — model gotowy do rozłożenia na komponenty z T6. */
export type FileActionDialogsModel = {
  rename: RenameDocumentDialogProps
  method: ChunkMethodDialogProps
  reparse: ReparseDialogProps
  /** Szuflada metadanych (WP E6-1b T5a). */
  meta: MetadataDrawerProps
  remove: {
    open: boolean
    count: number
    pending: boolean
    onConfirm: () => void
    onClose: () => void
  }
}

/** Akcje wiersza i zbiorcze wystawiane komponentowi zakładki. */
export type FileActionsController = {
  onParse: (doc: Pick<DocumentRow, 'id' | 'chunk_count'>) => void
  onStop: (doc: Pick<DocumentRow, 'id'>) => void
  onRename: (doc: DocumentRow) => void
  onDownload: (doc: Pick<DocumentRow, 'id' | 'name'>) => void
  onDelete: (doc: DocumentRow) => void
  onOpenMethod: (doc: DocumentRow) => void
  /** ⋮ → „Metadane”: otwiera szufladę edycji metadanych dokumentu (WP E6-1b T5a). */
  onMetadata: (doc: DocumentRow) => void
  /** Pozycje menu ⋮ wiersza (tryb compact): zmiana nazwy, pobranie, usunięcie, „Metadane”. */
  rowMenuItems: (doc: DocumentRow) => RowActionItem[]
  bulk: {
    onParse: () => void
    onCancel: () => void
    onEnable: () => void
    onDisable: () => void
    onDelete: () => void
  }
  dialogs: FileActionDialogsModel
}

/** Akcje zbiorcze czekające na potwierdzenie w dialogu. */
type PendingReparse = { ids: string[]; chunkCount: number }
type PendingRemove = { docs: DocumentRow[] }

export function useFileActions(datasetId: string, selected: DocumentRow[]): FileActionsController {
  const { t } = useTranslation()
  const { show } = useNotifications()

  const update = useUpdateDocument(datasetId)
  const remove = useDeleteDocuments(datasetId)
  const parse = useParseDocuments(datasetId)
  const stop = useStopDocuments(datasetId)
  const batch = useBatchUpdateStatus(datasetId)

  const [renameDoc, setRenameDoc] = useState<DocumentRow | null>(null)
  const [methodDoc, setMethodDoc] = useState<DocumentRow | null>(null)
  const [reparse, setReparse] = useState<PendingReparse | null>(null)
  const [removeTarget, setRemoveTarget] = useState<PendingRemove | null>(null)
  // Szuflada metadanych (WP E6-1b T5a): dokument z chwili kliknięcia ⋮ → „Metadane”.
  const [metaDoc, setMetaDoc] = useState<DocumentRow | null>(null)

  const notifyError = (error: unknown): void => {
    show(mutationMessage(error, t('datasets.files.error.generic'), t), { severity: 'error' })
  }

  const parseIds = (ids: string[]): void => {
    parse.mutate({ ids }, { onError: notifyError })
  }

  const selectedIds = selected.map((doc) => doc.id)

  /** Wiersz: z chunkami pytamy o potwierdzenie, bez chunków parsujemy od razu (§T7 p. 2). */
  const onParse: FileActionsController['onParse'] = (doc) => {
    if (hasChunks(doc)) {
      setReparse({ ids: [doc.id], chunkCount: doc.chunk_count })
      return
    }
    parseIds([doc.id])
  }

  const onStop: FileActionsController['onStop'] = (doc) => {
    stop.mutate({ ids: [doc.id] }, { onError: notifyError })
  }

  const onRename: FileActionsController['onRename'] = (doc) => {
    setRenameDoc(doc)
  }

  const onOpenMethod: FileActionsController['onOpenMethod'] = (doc) => {
    setMethodDoc(doc)
  }

  const onMetadata: FileActionsController['onMetadata'] = (doc) => setMetaDoc(doc)

  /** Pozycje ⋮ wiersza — z „Metadane” (kontrakt WP E6-1b §4); przeniesione z DatasetFilesTab. */
  const rowMenuItems: FileActionsController['rowMenuItems'] = (doc) => [
    {
      key: 'rename',
      label: t('datasets.files.action.rename'),
      icon: <EditOutlinedIcon />,
      onClick: () => onRename(doc),
    },
    {
      key: 'download',
      label: t('datasets.files.action.download'),
      icon: <DownloadOutlinedIcon />,
      onClick: () => onDownload(doc),
    },
    {
      key: 'delete',
      label: t('datasets.files.action.delete'),
      icon: <DeleteOutlineRoundedIcon />,
      onClick: () => onDelete(doc),
      disabled: !canDelete(doc),
    },
    {
      key: 'metadata',
      label: t('datasets.files.action.metadata'),
      icon: <LabelOutlinedIcon />,
      onClick: () => onMetadata(doc),
    },
  ]

  const onDownload: FileActionsController['onDownload'] = (doc) => {
    void downloadDocument(datasetId, doc).catch(notifyError)
  }

  const onDelete: FileActionsController['onDelete'] = (doc) => {
    setRemoveTarget({ docs: [doc] })
  }

  /** Zbiorczo: jeden dialog z SUMĄ chunków, gdy któryś zaznaczony dokument je ma (§T7 p. 2). */
  const onBulkParse = (): void => {
    if (selected.length === 0) return
    if (selected.some(hasChunks)) {
      setReparse({
        ids: selectedIds,
        chunkCount: selected.reduce((sum, doc) => sum + doc.chunk_count, 0),
      })
      return
    }
    parseIds(selectedIds)
  }

  const onBulkCancel = (): void => {
    stop.mutate({ ids: selectedIds }, { onError: notifyError })
  }

  const onBulkStatus = (enabled: boolean): void => {
    batch.mutate({ ids: selectedIds, enabled }, { onError: notifyError })
  }

  /** Dokumenty, których nie wolno usunąć, są pomijane; gdy nie ma żadnego — meldujemy blokadę. */
  const onBulkDelete = (): void => {
    const deletable = selected.filter(canDelete)
    if (deletable.length === 0) {
      show(t('datasets.files.action.deleteBlocked'), { severity: 'warning' })
      return
    }
    setRemoveTarget({ docs: deletable })
  }

  const confirmReparse: ReparseDialogProps['onConfirm'] = () => {
    if (reparse === null) return
    parseIds(reparse.ids)
    setReparse(null)
  }

  const confirmRemove = (): void => {
    if (removeTarget === null) return
    remove.mutate({ ids: removeTarget.docs.map((doc) => doc.id) }, { onError: notifyError })
    setRemoveTarget(null)
  }

  const dialogs: FileActionDialogsModel = {
    rename: {
      open: renameDoc !== null,
      name: renameDoc?.name ?? '',
      pending: update.isPending,
      onSave: (name) => {
        if (renameDoc === null) return
        update.mutate(
          { id: renameDoc.id, patch: { name } },
          {
            onError: notifyError,
            onSuccess: () => {
              show(t('files.toast.renamed'), { severity: 'success' })
            },
          },
        )
        setRenameDoc(null)
      },
      onClose: () => {
        setRenameDoc(null)
      },
    },
    method: {
      open: methodDoc !== null,
      method: methodDoc?.chunk_method ?? '',
      parserConfig: methodDoc?.parser_config ?? {},
      pending: update.isPending,
      // Kontrakt WP E5-H8c §3: PATCH {chunk_method, parser_config scalony w dialogu}.
      onSave: (method, parserConfig) => {
        if (methodDoc === null) return
        update.mutate(
          { id: methodDoc.id, patch: { chunk_method: method, parser_config: parserConfig } },
          { onError: notifyError },
        )
        setMethodDoc(null)
      },
      onClose: () => {
        setMethodDoc(null)
      },
    },
    reparse: {
      open: reparse !== null,
      chunkCount: reparse?.chunkCount ?? 0,
      onConfirm: confirmReparse,
      onClose: () => {
        setReparse(null)
      },
    },
    meta: {
      open: metaDoc !== null,
      datasetId,
      doc: metaDoc,
      onClose: () => {
        setMetaDoc(null)
      },
    },
    remove: {
      open: removeTarget !== null,
      count: removeTarget?.docs.length ?? 0,
      pending: remove.isPending,
      onConfirm: confirmRemove,
      onClose: () => {
        setRemoveTarget(null)
      },
    },
  }

  return {
    onParse,
    onStop,
    onRename,
    onDownload,
    onDelete,
    onOpenMethod,
    onMetadata,
    rowMenuItems,
    bulk: {
      onParse: onBulkParse,
      onCancel: onBulkCancel,
      onEnable: () => {
        onBulkStatus(true)
      },
      onDisable: () => {
        onBulkStatus(false)
      },
      onDelete: onBulkDelete,
    },
    dialogs,
  }
}
