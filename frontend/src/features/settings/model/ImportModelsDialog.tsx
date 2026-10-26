/**
 * Dialog „Pobierz z /v1/models” (brief E3-6c1 T6 pkt 4): po otwarciu pyta o listę bramki
 * (`?supported=true`), pozwala zaznaczyć wiele nazw i wybrać dla nich typ, a import wysyła
 * kolejne `POST …/models` (jedno na nazwę). Nazwy już obecne w instancji są pomijane,
 * a podsumowanie pokazuje liczbę dodanych i komunikaty błędów (kontrakt §0).
 * Lista ma wyszukiwarkę (po fragmencie nazwy), a wybrany typ działa też jako filtr: bramka OpenRouter
 * podaje typy modeli (`model_type`), więc pokazujemy modele tego typu i te o nieznanym typie.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { MODEL_TYPES } from '../constants'
import type { ModelType } from '../constants'
import { supportedModelsQueryOptions, useAddInstanceModel } from '../providerQueries'
import type { SupportedModel } from '../providerQueries'

import { DEFAULT_MAX_TOKENS, buildAddModelBody } from './AddModelDialog'

/** Wynik importu: ile modeli dodano i jakie komunikaty błędów wróciły z API. */
type ImportResult = { added: number; errors: string[] }

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

/**
 * Czy model z bramki pasuje do wybranego typu importu: nieznany typ pokazujemy zawsze (nie wiemy,
 * czy nie pasuje), a „vision” to modele czatu z obrazem — katalog nie odróżnia ich od `chat`.
 */
export function matchesType(item: SupportedModel, type: ModelType): boolean {
  if (item.model_type == null) return true
  return type === 'vision' ? item.model_type === 'chat' : item.model_type === type
}

export type ImportModelsDialogProps = {
  instanceId: string
  /** Nazwy modeli już obecnych w instancji — pomijamy je przy imporcie (brief pkt 4). */
  existingNames: string[]
  open: boolean
  onClose: () => void
}

export function ImportModelsDialog(props: ImportModelsDialogProps): JSX.Element {
  const { instanceId, existingNames, open, onClose } = props
  const { t } = useTranslation()
  const supported = useQuery(supportedModelsQueryOptions(instanceId, open))
  const add = useAddInstanceModel(instanceId)
  const [selected, setSelected] = useState<string[]>([])
  const [type, setType] = useState<ModelType>('chat')
  const [search, setSearch] = useState('')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [pending, setPending] = useState(false)

  const existing = new Set(existingNames)
  const items = supported.data ?? []
  const needle = search.trim().toLowerCase()
  const visible = items.filter(
    (item) => matchesType(item, type) && item.name.toLowerCase().includes(needle),
  )
  const available = visible.filter((item) => !existing.has(item.name))
  // Import i liczniki dotyczą tylko widocznych pozycji: zaznaczone, a potem odfiltrowane modele
  // nie trafiają do instancji z innym typem niż ten, który widzi użytkownik.
  const visibleNames = new Set(visible.map((item) => item.name))
  const chosen = selected.filter((name) => visibleNames.has(name))
  const allSelected =
    available.length > 0 && available.every((item) => selected.includes(item.name))

  function toggle(name: string, checked: boolean): void {
    setSelected((current) =>
      checked ? [...current, name] : current.filter((item) => item !== name),
    )
  }

  function toggleAll(checked: boolean): void {
    const names = available.map((item) => item.name)
    setSelected((current) =>
      checked
        ? [...new Set([...current, ...names])]
        : current.filter((name) => !names.includes(name)),
    )
  }

  function close(): void {
    setSelected([])
    setSearch('')
    setResult(null)
    onClose()
  }

  /** Kolejne POST-y: jedno żądanie na zaznaczoną, jeszcze nieistniejącą nazwę. */
  async function runImport(): Promise<void> {
    const names = chosen.filter((name) => !existing.has(name))
    setPending(true)
    let added = 0
    const errors: string[] = []
    for (const name of names) {
      try {
        await add.mutateAsync(
          buildAddModelBody({
            name,
            type,
            maxTokens: DEFAULT_MAX_TOKENS,
            // Import nie ustawia współbieżności — `extra` dostaje ją dopiero edycja (E5-H8c T3).
            concurrency: '',
            dimension: '',
          }),
        )
        added += 1
      } catch (error) {
        errors.push(
          error instanceof ApiError && error.message !== ''
            ? error.message
            : t('settings.models.error'),
        )
      }
    }
    setPending(false)
    setResult({ added, errors })
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('settings.models.importTitle')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {supported.isError ? (
            <Alert severity="error">
              {errorText(supported.error, t('settings.error.title'), t('settings.models.error'))}
            </Alert>
          ) : null}

          {result === null ? null : (
            <Alert severity={result.errors.length > 0 ? 'error' : 'success'}>
              <Typography variant="body2">
                {t('settings.models.importSummary', { count: result.added })}
              </Typography>
              {result.errors.map((message) => (
                <Typography key={message} variant="body2">
                  {message}
                </Typography>
              ))}
            </Alert>
          )}

          {supported.isPending ? (
            <Skeleton variant="rounded" height={120} data-testid="import-models-loading" />
          ) : items.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('settings.models.importEmpty')}
            </Typography>
          ) : (
            <>
              <TextField
                fullWidth
                size="small"
                type="search"
                label={t('settings.models.importSearch')}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                data-testid="import-model-search"
              />
              <Typography variant="caption" color="text.secondary">
                {t('settings.models.importShown', { shown: visible.length, total: items.length })}
              </Typography>
              <Box sx={{ maxHeight: 240, overflowY: 'auto' }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={allSelected}
                      indeterminate={!allSelected && selected.length > 0}
                      onChange={(event) => toggleAll(event.target.checked)}
                    />
                  }
                  label={t('settings.models.selectAll')}
                />
                {visible.length === 0 ? (
                  <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>
                    {t('settings.models.importNoMatch')}
                  </Typography>
                ) : null}
                {visible.map((item) => (
                  <FormControlLabel
                    key={item.name}
                    control={
                      <Checkbox
                        checked={selected.includes(item.name)}
                        disabled={existing.has(item.name)}
                        onChange={(event) => toggle(item.name, event.target.checked)}
                      />
                    }
                    label={item.name}
                  />
                ))}
              </Box>
            </>
          )}

          <TextField
            select
            fullWidth
            size="small"
            label={t('settings.models.importType')}
            value={type}
            onChange={(event) => setType(event.target.value as ModelType)}
            helperText={t('settings.models.importTypeHint')}
            data-testid="import-model-type"
          >
            {MODEL_TYPES.map((modelType) => (
              <MenuItem key={modelType} value={modelType}>
                {t(`settings.models.type.${modelType}`)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('settings.common.cancel')}</Button>
        <Button
          variant="contained"
          loading={pending}
          disabled={chosen.length === 0}
          onClick={() => void runImport()}
        >
          {t('settings.models.importSubmit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
