/**
 * Dialog „Połącz z datasetami” (kontrakt WP E4-5c §7): lista datasetów z `datasetsListQueryOptions`
 * jako wielokrotny `Checkbox`, przełącznik „Dopisuj” (`mode: 'add'`, domyślnie nie wysyłany).
 * Przycisk `files.link.confirm` nieaktywny bez wyboru. Sukces → toast `files.toast.linked` i `onClose`;
 * brak datasetów → `files.link.noDatasets`; błąd koperty → `Alert` z `errorText` (T5b).
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import Switch from '@mui/material/Switch'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { datasetsListQueryOptions } from '../datasets/queries'
import useNotifications from '../../hooks/useNotifications/useNotifications'
import { errorText } from '../../lib/errorText'
import { useLinkFiles } from './mutations'
import type { FileItem } from './queries'

export type LinkFilesDialogProps = {
  files: FileItem[] | null
  onClose: () => void
}

export function LinkFilesDialog(props: LinkFilesDialogProps) {
  const { files, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const link = useLinkFiles()
  const datasets = useQuery(datasetsListQueryOptions())

  const [selected, setSelected] = useState<string[]>([])
  const [append, setAppend] = useState(false)

  // Reset wyboru i trybu „Dopisuj” przy każdym nowym zestawie plików (korekta stanu w renderze).
  const [openedFiles, setOpenedFiles] = useState(files)
  if (openedFiles !== files) {
    setOpenedFiles(files)
    if (files !== null) {
      setSelected([])
      setAppend(false)
    }
  }

  const close = () => {
    link.reset()
    onClose()
  }

  const toggle = (id: string) => {
    setSelected((previous) =>
      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id],
    )
  }

  const submit = () => {
    if (files === null || selected.length === 0) return
    link.mutate(
      { fileIds: files.map((file) => file.id), kbIds: selected, mode: append ? 'add' : undefined },
      {
        onSuccess: () => {
          show(t('files.toast.linked'), { severity: 'success' })
          close()
        },
      },
    )
  }

  const noDatasets = datasets.isSuccess && datasets.data.length === 0

  return (
    <Dialog open={files !== null} onClose={close} maxWidth="xs" fullWidth>
      <DialogTitle>{t('files.link.title')}</DialogTitle>
      <DialogContent>
        {link.error !== null ? <Alert severity="error">{errorText(link.error, t)}</Alert> : null}
        <Typography variant="body2" color="text.secondary">
          {t('files.link.hint')}
        </Typography>
        {noDatasets ? (
          <Typography variant="body2" data-testid="files-link-empty">
            {t('files.link.noDatasets')}
          </Typography>
        ) : (
          <List dense data-testid="files-link-datasets">
            {(datasets.data ?? []).map((dataset) => (
              <ListItem key={dataset.id} disablePadding>
                <FormControlLabel
                  control={
                    <Checkbox
                      data-testid={`files-link-dataset-${dataset.id}`}
                      checked={selected.includes(dataset.id)}
                      onChange={() => toggle(dataset.id)}
                    />
                  }
                  label={dataset.name}
                />
              </ListItem>
            ))}
          </List>
        )}
        <FormControlLabel
          control={
            <Switch
              data-testid="files-link-add"
              checked={append}
              onChange={(event) => setAppend(event.target.checked)}
            />
          }
          label={t('files.link.add')}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('common.cancel')}</Button>
        <Button
          data-testid="files-link-confirm"
          variant="contained"
          disabled={selected.length === 0}
          loading={link.isPending}
          onClick={submit}
        >
          {t('files.link.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
