/**
 * Lista instancji dostawcy (brief E3-6c1 T5b pkt 1, 4, 6, 7): nagłówek, lista z wyborem instancji,
 * a dla superusera dodawanie, edycja, weryfikacja (w dialogu) i usuwanie z potwierdzeniem.
 * Instancja `default` jest środkowiskowa — nosi `Chip` i nie ma akcji zapisu (kontrakt §0).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import AddRoundedIcon from '@mui/icons-material/AddRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { DEFAULT_INSTANCE_NAME } from '../constants'
import { instancesQueryOptions, useDeleteInstances } from '../providerQueries'
import type { ProviderInstance } from '../providerQueries'
import { useIsSuperuser } from '../useIsSuperuser'

import { InstanceDialog } from './InstanceDialog'

export type InstancesPanelProps = {
  selectedId: string | null
  onSelect: (id: string) => void
}

/** Otwarty dialog: tworzenie albo edycja wskazanej instancji; `null` = żaden. */
type DialogState = { kind: 'create' } | { kind: 'edit'; instance: ProviderInstance } | null

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export function InstancesPanel(props: InstancesPanelProps): JSX.Element {
  const { selectedId, onSelect } = props
  const { t } = useTranslation()
  const isSuperuser = useIsSuperuser()
  const instances = useQuery(instancesQueryOptions())
  const deleteInstances = useDeleteInstances()
  const [dialog, setDialog] = useState<DialogState>(null)
  const [pendingDelete, setPendingDelete] = useState<ProviderInstance | null>(null)

  const items = instances.data ?? []

  /** Usuwanie kończy się tak samo przy sukcesie i błędzie — komunikat trafia do panelu. */
  function confirmDelete(): void {
    if (pendingDelete === null) return
    deleteInstances.mutate([pendingDelete.id], { onSettled: () => setPendingDelete(null) })
  }

  return (
    <Stack spacing={2}>
      {/* Nagłówek w kolumnie (T8, D7): długi tytuł („Dostawca: OpenAI-compatible / LiteLLM”)
          zawija się obok przycisku w układzie poziomym i ściska „+ Dodaj instancję” (odstęp ~0,
          1280 px, PL i EN). Tytuł nad przyciskiem z odstępem 8 px (`spacing={1}`) — także na
          md/lg; kontrakt WP E5-H8c §4 (< sm: kolumna pod nagłówkiem) spełniony tym samym. */}
      <Stack spacing={1} sx={{ alignItems: 'flex-start' }}>
        <Typography variant="h6">{t('settings.instances.providerTitle')}</Typography>
        {isSuperuser ? (
          <Button
            size="small"
            startIcon={<AddRoundedIcon />}
            onClick={() => setDialog({ kind: 'create' })}
            sx={{ whiteSpace: 'nowrap' }}
          >
            {t('settings.instances.add')}
          </Button>
        ) : null}
      </Stack>

      {deleteInstances.isError ? (
        <Alert severity="error">
          {errorText(
            deleteInstances.error,
            t('settings.error.title'),
            t('settings.instances.error'),
          )}
        </Alert>
      ) : null}

      {instances.isError ? (
        // Kontrakt WP E3-7 §C6: błąd zapytania to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
        <QueryError
          message={errorText(
            instances.error,
            t('settings.error.title'),
            t('settings.instances.error'),
          )}
          onRetry={() => void instances.refetch()}
        />
      ) : instances.isPending ? (
        <Typography variant="body2" color="text.secondary">
          {t('settings.common.loading')}
        </Typography>
      ) : items.length === 0 ? (
        <EmptyState title={t('settings.instances.empty')} />
      ) : (
        <List>
          {items.map((instance) => {
            const managed = instance.instance_name.toLowerCase() === DEFAULT_INSTANCE_NAME
            const selected = instance.id === selectedId
            return (
              // `ListItem` renderuje `<li>` — bez niego `ListItemButton` (domyślnie `div`)
              // byłby bezpośrednim dzieckiem `ul` i łamał regułę axe `list` (WP E3-7 T7).
              <ListItem key={instance.id} disablePadding>
                <ListItemButton
                  selected={selected}
                  aria-current={selected ? 'true' : undefined}
                  data-testid={`instance-item-${instance.id}`}
                  onClick={() => onSelect(instance.id)}
                >
                  <ListItemText primary={instance.instance_name} />
                  {managed ? (
                    <Chip size="small" label={t('settings.instances.managed')} sx={{ mr: 1 }} />
                  ) : null}
                  {isSuperuser && !managed ? (
                    <>
                      <IconButton
                        size="small"
                        aria-label={t('settings.instances.editAria', {
                          name: instance.instance_name,
                        })}
                        onClick={(event) => {
                          event.stopPropagation()
                          setDialog({ kind: 'edit', instance })
                        }}
                      >
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        aria-label={t('settings.instances.deleteAria', {
                          name: instance.instance_name,
                        })}
                        onClick={(event) => {
                          event.stopPropagation()
                          setPendingDelete(instance)
                        }}
                      >
                        <DeleteOutlineRoundedIcon fontSize="small" />
                      </IconButton>
                    </>
                  ) : null}
                </ListItemButton>
              </ListItem>
            )
          })}
        </List>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('settings.instances.deleteTitle')}
        message={t('settings.instances.deleteMessage', {
          name: pendingDelete?.instance_name ?? '',
        })}
        confirmLabel={t('settings.common.delete')}
        cancelLabel={t('settings.common.cancel')}
        loading={deleteInstances.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      {dialog === null ? null : (
        <InstanceDialog
          instance={dialog.kind === 'edit' ? dialog.instance : undefined}
          onClose={() => setDialog(null)}
        />
      )}
    </Stack>
  )
}
