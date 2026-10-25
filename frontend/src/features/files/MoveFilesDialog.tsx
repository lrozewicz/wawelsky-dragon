/**
 * Dialog „Przenieś pliki” (kontrakt WP E4-5c §7): leniwe drzewo folderów (`folderChildrenQueryOptions`)
 * z węzłem „root” zawsze widocznym. Rozwijanie węzła dociąga dzieci; liście (`has_child_folder === false`)
 * nie mają strzałki. Foldery będące źródłami są wyłączone. Identyfikator roota bierzemy z listingu
 * (`parentFolder.id`), bo drzewo go nie zna. Sukces → toast i `onClose`; błąd koperty → `Alert`.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import Typography from '@mui/material/Typography'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'

import useNotifications from '../../hooks/useNotifications/useNotifications'
import { errorText } from '../../lib/errorText'
import { useMoveFiles } from './mutations'
import { DEFAULT_FILES_QUERY, filesListQueryOptions, folderChildrenQueryOptions } from './queries'
import type { FileItem } from './queries'

/** Klucz węzła roota w drzewie — identyfikator folderu nadrzędnego nie jest znany przed listingiem. */
const ROOT_KEY = '__root__'

type FolderNodeProps = {
  nodeKey: string
  nodeId: string | undefined
  label: string
  expandable: boolean
  disabled: boolean
  depth: number
  selectedKey: string | null
  onSelect: (key: string) => void
  sourceFolderIds: ReadonlySet<string>
}

/** Węzeł drzewa: własny stan rozwinięcia, dzieci pobierane dopiero po rozwinięciu. */
function FolderNode(props: FolderNodeProps) {
  const {
    nodeKey,
    nodeId,
    label,
    expandable,
    disabled,
    depth,
    selectedKey,
    onSelect,
    sourceFolderIds,
  } = props
  const [expanded, setExpanded] = useState(false)
  // Folder źródłowy jest wyłączony i nie rozwijamy go (kontrakt §7: cel ≠ źródło ani jego potomek).
  const canExpand = expandable && !disabled
  const children = useQuery({
    ...folderChildrenQueryOptions(nodeId),
    enabled: expanded && canExpand,
  })
  const selected = selectedKey === nodeKey

  return (
    <>
      <ListItem disablePadding sx={{ pl: depth * 2 }}>
        {canExpand ? (
          <IconButton
            size="small"
            aria-label={label}
            data-testid={`folder-expand-${nodeKey}`}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
          </IconButton>
        ) : (
          <Box sx={{ width: 34 }} />
        )}
        <ListItemButton
          selected={selected}
          aria-selected={selected}
          aria-disabled={disabled}
          disabled={disabled}
          data-testid={`folder-node-${nodeKey}`}
          onClick={() => onSelect(nodeKey)}
        >
          <ListItemText primary={label} />
        </ListItemButton>
      </ListItem>
      {expanded
        ? children.data?.map((child) => (
            <FolderNode
              key={child.id}
              nodeKey={child.id}
              nodeId={child.id}
              label={child.name}
              expandable={child.has_child_folder === true}
              disabled={sourceFolderIds.has(child.id)}
              depth={depth + 1}
              selectedKey={selectedKey}
              onSelect={onSelect}
              sourceFolderIds={sourceFolderIds}
            />
          ))
        : null}
    </>
  )
}

export type MoveFilesDialogProps = {
  files: FileItem[] | null
  onClose: () => void
}

export function MoveFilesDialog(props: MoveFilesDialogProps) {
  const { files, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const move = useMoveFiles()
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const sourceFolderIds = new Set(
    (files ?? []).filter((file) => file.type === 'folder').map((file) => file.id),
  )

  // Dzieci roota znamy od razu (decydują o stanie „brak folderów”); listing daje id roota.
  const rootChildren = useQuery(folderChildrenQueryOptions(undefined))
  const rootList = useQuery(filesListQueryOptions(DEFAULT_FILES_QUERY))
  const rootId = rootList.data?.parentFolder?.id

  // Reset zaznaczenia przy każdym nowym zestawie plików (korekta stanu w renderze).
  const [openedFiles, setOpenedFiles] = useState(files)
  if (openedFiles !== files) {
    setOpenedFiles(files)
    if (files !== null) setSelectedKey(null)
  }

  const destId = selectedKey === null ? undefined : selectedKey === ROOT_KEY ? rootId : selectedKey

  const close = () => {
    move.reset()
    onClose()
  }

  const submit = () => {
    if (files === null || destId === undefined) return
    move.mutate(
      { srcIds: files.map((file) => file.id), destId },
      {
        onSuccess: () => {
          show(t('files.toast.moved'), { severity: 'success' })
          close()
        },
      },
    )
  }

  const noFolders = rootChildren.isSuccess && rootChildren.data.length === 0

  return (
    <Dialog open={files !== null} onClose={close} maxWidth="xs" fullWidth>
      <DialogTitle>{t('files.move.title')}</DialogTitle>
      <DialogContent>
        {move.error !== null ? <Alert severity="error">{errorText(move.error, t)}</Alert> : null}
        <Typography variant="body2" color="text.secondary">
          {t('files.move.hint')}
        </Typography>
        {noFolders ? (
          <Typography variant="body2" data-testid="files-move-empty">
            {t('files.move.noFolders')}
          </Typography>
        ) : (
          <List dense>
            <FolderNode
              nodeKey={ROOT_KEY}
              nodeId={undefined}
              label={t('files.move.root')}
              expandable
              disabled={false}
              depth={0}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
              sourceFolderIds={sourceFolderIds}
            />
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('common.cancel')}</Button>
        <Button
          data-testid="files-move-confirm"
          variant="contained"
          disabled={destId === undefined}
          loading={move.isPending}
          onClick={submit}
        >
          {t('files.move.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
