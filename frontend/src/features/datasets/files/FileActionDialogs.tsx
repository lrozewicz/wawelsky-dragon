/**
 * Dialogi akcji zakładki Pliki (kontrakt WP E3-3b §T7): zmiana nazwy, metoda chunkowania, ponowne
 * parsowanie i potwierdzenie usunięcia. Komponent jest czysto prezentacyjny — stan i mutacje wnosi
 * `useFileActions`, dzięki czemu `DatasetFilesTab` zostaje przy siatce i toolbarze.
 * Od WP E6-1b T5a także szuflada metadanych (`MetadataDrawer`), bo jej stan trzyma `useFileActions`.
 */

import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { ChunkMethodDialog } from './ChunkMethodDialog'
import { MetadataDrawer } from './MetadataDrawer'
import { RenameDocumentDialog } from './RenameDocumentDialog'
import { ReparseDialog } from './ReparseDialog'
import type { FileActionDialogsModel } from './useFileActions'

export type FileActionDialogsProps = {
  model: FileActionDialogsModel
}

export function FileActionDialogs(props: FileActionDialogsProps) {
  const { model } = props
  const { t } = useTranslation()

  return (
    <>
      <RenameDocumentDialog {...model.rename} />
      <ChunkMethodDialog {...model.method} />
      <ReparseDialog {...model.reparse} />
      <MetadataDrawer {...model.meta} />
      <ConfirmDialog
        open={model.remove.open}
        title={t('datasets.files.delete.title')}
        message={t('datasets.files.delete.body', { n: model.remove.count })}
        confirmLabel={t('datasets.files.delete.confirm')}
        cancelLabel={t('common.cancel')}
        loading={model.remove.pending}
        onConfirm={model.remove.onConfirm}
        onCancel={model.remove.onClose}
      />
    </>
  )
}
