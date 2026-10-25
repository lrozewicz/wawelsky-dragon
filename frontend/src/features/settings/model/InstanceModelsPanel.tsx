/**
 * Panel modeli wybranej instancji (brief E3-6c1 T6): nagłówek z nazwą instancji, siatka modeli
 * z przełącznikiem włączenia, edycją (✎) i usuwaniem oraz wejścia do dialogów „Dodaj model”
 * i importu z bramki. Zapis widzi wyłącznie superuser (kontrakt §0). Siatkę ładujemy przez
 * `lazy`, żeby `@mui/x-data-grid` nie trafiał do chunku strony (wzór: `settings/api/ApiKeysPage.tsx`).
 */

import { Suspense, lazy, useState } from 'react'
import type { JSX } from 'react'
import AddRoundedIcon from '@mui/icons-material/AddRounded'
import CloudDownloadRoundedIcon from '@mui/icons-material/CloudDownloadRounded'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'
import {
  instanceModelsQueryOptions,
  useDeleteInstanceModels,
  useUpdateInstanceModel,
} from '../providerQueries'
import type { InstanceModel, ProviderInstance } from '../providerQueries'
import { settingsKeys } from '../queries'
import { useIsSuperuser } from '../useIsSuperuser'

import { AddModelDialog } from './AddModelDialog'
import { EditModelDialog } from './EditModelDialog'
import { ImportModelsDialog } from './ImportModelsDialog'

/** Wysokość szkieletu siatki — jak w trasie `user-setting/model`. */
const GRID_SKELETON_HEIGHT = 420

const InstanceModelsGrid = lazy(async () => {
  const module = await import('./InstanceModelsGrid')
  return { default: module.InstanceModelsGrid }
})

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export type InstanceModelsPanelProps = {
  instance: ProviderInstance | null
}

export function InstanceModelsPanel(props: InstanceModelsPanelProps): JSX.Element {
  const { t } = useTranslation()
  const { instance } = props

  if (instance === null) {
    return <EmptyState title={t('settings.models.selectInstance')} />
  }

  return <InstanceModelsContent instance={instance} />
}

type InstanceModelsContentProps = {
  instance: ProviderInstance
}

/**
 * Treść panelu istnieje tylko dla wybranej instancji — mutacje dostają jej `id`
 * (hooki muszą stać bezwarunkowo, stąd rozdział od gałęzi `instance === null`).
 */
function InstanceModelsContent(props: InstanceModelsContentProps): JSX.Element {
  const { instance } = props
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const isSuperuser = useIsSuperuser()
  const models = useQuery(instanceModelsQueryOptions(instance.id))
  const update = useUpdateInstanceModel(instance.id)
  const remove = useDeleteInstanceModels(instance.id)
  const [addOpen, setAddOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  // Model edytowany trzymamy także po zamknięciu dialogu (zostaje podczas animacji wyjścia
  // i przywracania fokusu na ✎); otwarcie nowego nadpisuje go, a formularz i tak resetuje
  // stan z propsa (`EditModelDialog`, wzór „reset przy otwarciu”).
  const [editing, setEditing] = useState<InstanceModel | null>(null)
  const [editOpen, setEditOpen] = useState(false)

  const rows = models.data ?? []

  /**
   * Zmiana statusu: ciało zawiera tylko `status` — pozostałe pola są w schemacie opcjonalne
   * (po E2-H2), więc typ pasuje bez rzutowania (wzór: `buildInstanceCreate` w `instanceForm.ts`).
   * Po błędzie odświeżamy listę, żeby przełącznik wrócił do stanu z serwera (brief pkt 2).
   */
  function toggleStatus(row: InstanceModel, active: boolean): void {
    update.reset()
    update.mutate(
      {
        modelName: row.name,
        body: {
          status: active ? 'active' : 'inactive',
        },
      },
      {
        onError: () => {
          void queryClient.invalidateQueries({ queryKey: settingsKeys.instanceModels(instance.id) })
        },
      },
    )
  }

  function confirmDelete(): void {
    if (pendingDelete === null) return
    remove.reset()
    remove.mutate([pendingDelete], { onSettled: () => setPendingDelete(null) })
  }

  return (
    <Stack spacing={2}>
      {/* Na < sm przyciski schodzą do kolumny pod nagłówkiem (kontrakt WP E5-H8c §4) — długa
          nazwa instancji nie wypycha ich poza okno 390 px (overflow-page, SC-E5-H8c-05). */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        sx={{ alignItems: { xs: 'flex-start', sm: 'center' }, justifyContent: 'space-between' }}
      >
        <Typography variant="h6" sx={{ overflowWrap: 'anywhere' }}>
          {t('settings.models.title', { name: instance.instance_name })}
        </Typography>
        {isSuperuser ? (
          // `whiteSpace: 'nowrap'` — nigdy łamanie tekstu wewnątrz przycisku (kontrakt §4);
          // para „Dodaj model” + „Pobierz z /v1/models” mieści się w 390 px także po angielsku.
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              startIcon={<AddRoundedIcon />}
              onClick={() => setAddOpen(true)}
              sx={{ whiteSpace: 'nowrap' }}
            >
              {t('settings.models.add')}
            </Button>
            <Button
              size="small"
              startIcon={<CloudDownloadRoundedIcon />}
              onClick={() => setImportOpen(true)}
              sx={{ whiteSpace: 'nowrap' }}
            >
              {t('settings.models.import')}
            </Button>
          </Stack>
        ) : null}
      </Stack>

      {update.isError ? (
        <Alert severity="error">
          {errorText(update.error, t('settings.error.title'), t('settings.models.error'))}
        </Alert>
      ) : null}
      {remove.isError ? (
        <Alert severity="error">
          {errorText(remove.error, t('settings.error.title'), t('settings.models.error'))}
        </Alert>
      ) : null}

      {models.isError ? (
        // Kontrakt WP E3-7 §C6: błąd zapytania to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
        <QueryError
          message={errorText(models.error, t('settings.error.title'), t('settings.models.error'))}
          onRetry={() => void models.refetch()}
        />
      ) : (
        <Suspense fallback={<Skeleton variant="rounded" height={GRID_SKELETON_HEIGHT} />}>
          <InstanceModelsGrid
            rows={rows}
            loading={models.isPending}
            isSuperuser={isSuperuser}
            onToggle={toggleStatus}
            onEdit={(row) => {
              setEditing(row)
              setEditOpen(true)
            }}
            onDelete={setPendingDelete}
          />
        </Suspense>
      )}

      <AddModelDialog instanceId={instance.id} open={addOpen} onClose={() => setAddOpen(false)} />
      <EditModelDialog
        instanceId={instance.id}
        open={editOpen}
        model={editing}
        onClose={() => setEditOpen(false)}
      />
      <ImportModelsDialog
        instanceId={instance.id}
        existingNames={rows.map((row) => row.name)}
        open={importOpen}
        onClose={() => setImportOpen(false)}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('settings.models.deleteTitle')}
        message={t('settings.models.deleteMessage', { name: pendingDelete ?? '' })}
        confirmLabel={t('settings.common.delete')}
        cancelLabel={t('settings.common.cancel')}
        loading={remove.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </Stack>
  )
}
