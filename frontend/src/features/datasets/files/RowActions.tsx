/**
 * Akcje pojedynczego wiersza listy plików (kontrakt WP E3-3b §T6): zmiana nazwy, pobranie,
 * usunięcie. Komponent jest czysto prezentacyjny — decyzje i mutacje należą do wołającego (T7).
 * Usunięcie jest zablokowane, gdy dokument się parsuje (`canDelete`): przycisk jest wtedy
 * nieaktywny i objęty podpowiedzią. MUI nie pokazuje `Tooltip`a na nieaktywnym przycisku,
 * dlatego przycisk wraca do drzewa opakowany w `span`.
 * Od WP E6-1b T5a na końcu stoi ⋮ (`RowActionsMenu`) z pozycją „Metadane” — wejście do szuflady
 * edycji `meta_fields` (kontrakt WP E6-1b §4); testy e2e klikają `data-testid="row-actions-menu"`
 * także na desktopie.
 */

import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import LabelOutlinedIcon from '@mui/icons-material/LabelOutlined'
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import { useTranslation } from 'react-i18next'

import { RowActionsMenu } from '../../../components/RowActionsMenu'
import { canDelete } from './parsingState'
import type { DocumentRow } from './queries'

export type RowActionsProps = {
  doc: Pick<DocumentRow, 'id' | 'name' | 'run' | 'progress' | 'chunk_count'>
  onRename: () => void
  onDownload: () => void
  onDelete: () => void
  /** ⋮ → „Metadane”: otwiera szufladę edycji metadanych dokumentu (WP E6-1b T5a). */
  onMetadata: () => void
  /** ⋮ → „Metoda chunkowania”: dialog zmiany metody pliku (kolumna z chipem jest ukryta < xl, E67-z2 T6). */
  onOpenMethod?: () => void
}

export function RowActions(props: RowActionsProps) {
  const { doc, onRename, onDownload, onDelete, onMetadata, onOpenMethod } = props
  const { t } = useTranslation()
  const deletable = canDelete(doc)

  const deleteButton = (
    <IconButton
      size="small"
      data-testid={`row-delete-${doc.id}`}
      aria-label={t('datasets.files.action.delete')}
      disabled={!deletable}
      onClick={onDelete}
    >
      <DeleteOutlineRoundedIcon />
    </IconButton>
  )

  return (
    // Odstęp 2 px i przyciski `small` (32 px) — kolumna akcji mieści 3 przyciski w 125 px przy
    // 1280 px bez przewijania poziomego (T7).
    <Stack direction="row" spacing={0.25} sx={{ alignItems: 'center' }}>
      <IconButton
        size="small"
        data-testid={`row-rename-${doc.id}`}
        aria-label={t('datasets.files.action.rename')}
        onClick={onRename}
      >
        <EditOutlinedIcon />
      </IconButton>
      <IconButton
        size="small"
        data-testid={`row-download-${doc.id}`}
        aria-label={t('datasets.files.action.download')}
        onClick={onDownload}
      >
        <DownloadOutlinedIcon />
      </IconButton>
      {deletable ? (
        deleteButton
      ) : (
        <Tooltip title={t('datasets.files.action.deleteBlocked')}>
          <span>{deleteButton}</span>
        </Tooltip>
      )}
      <RowActionsMenu
        ariaLabel={t('common.rowActions')}
        items={[
          ...(onOpenMethod === undefined
            ? []
            : [
                {
                  key: 'method',
                  label: t('datasets.files.col.method'),
                  icon: <TuneOutlinedIcon />,
                  onClick: onOpenMethod,
                },
              ]),
          {
            key: 'metadata',
            label: t('datasets.files.action.metadata'),
            icon: <LabelOutlinedIcon />,
            onClick: onMetadata,
          },
        ]}
      />
    </Stack>
  )
}
