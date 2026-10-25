/**
 * Zestaw dialogów listy Plików (kontrakt WP E4-5c §7, T4). Czysto prezentacyjny: dostaje cele
 * i callbacki od `useFilesActions`, a sam tylko renderuje okna. `UploadFilesDialog`
 * i `NewFolderDialog` dostają bieżący folder jako `parentId` (root → `undefined`), a usunięcie
 * potwierdza wspólny `ConfirmDialog`; podgląd otwiera `DocumentPreviewDrawer` (features/chats).
 */

import type { JSX } from 'react'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DocumentPreviewDrawer } from '../chats/preview/DocumentPreviewDrawer'

import { LinkFilesDialog } from './LinkFilesDialog'
import { MoveFilesDialog } from './MoveFilesDialog'
import { NewFolderDialog } from './NewFolderDialog'
import { RenameFileDialog } from './RenameFileDialog'
import { UploadFilesDialog } from './UploadFilesDialog'
import type { FilesDialogRequest } from './useFilesActions'
import type { FileItem } from './queries'

export type FilesDialogsProps = {
  parentId: string | undefined
  dialog: FilesDialogRequest
  renameTarget: FileItem | null
  moveTargets: FileItem[] | null
  linkTargets: FileItem[] | null
  deleteTargets: FileItem[] | null
  previewDoc: { id: string; name: string } | null
  deleting: boolean
  onCloseDialog: () => void
  onCloseRename: () => void
  onCloseMove: () => void
  onCloseLink: () => void
  onCloseDelete: () => void
  onClosePreview: () => void
  onConfirmDelete: () => void
}

export function FilesDialogs(props: FilesDialogsProps): JSX.Element {
  const { t } = useTranslation()
  const count = props.deleteTargets?.length ?? 0

  return (
    <>
      <UploadFilesDialog
        open={props.dialog === 'upload'}
        parentId={props.parentId}
        onClose={props.onCloseDialog}
      />
      <NewFolderDialog
        open={props.dialog === 'folder'}
        parentId={props.parentId}
        onClose={props.onCloseDialog}
      />
      <RenameFileDialog file={props.renameTarget} onClose={props.onCloseRename} />
      <MoveFilesDialog files={props.moveTargets} onClose={props.onCloseMove} />
      <LinkFilesDialog files={props.linkTargets} onClose={props.onCloseLink} />
      <ConfirmDialog
        open={props.deleteTargets !== null}
        title={t('files.delete.title')}
        message={t('files.delete.body', { count })}
        confirmLabel={t('files.delete.confirm')}
        cancelLabel={t('common.cancel')}
        loading={props.deleting}
        onConfirm={props.onConfirmDelete}
        onCancel={props.onCloseDelete}
      />
      <DocumentPreviewDrawer
        documentId={props.previewDoc?.id ?? null}
        documentName={props.previewDoc?.name}
        onClose={props.onClosePreview}
      />
    </>
  )
}
