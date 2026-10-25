/**
 * Dialog „Metoda chunkowania” dokumentu (kontrakt WP E3-3b §T6, rozbudowa WP E5-H8c §3).
 * Pokazuje FAKTYCZNĄ konfigurację pliku: metodę, Parser PDF (opcje jak w konfiguracji datasetu —
 * `LAYOUT_OPTIONS` + modele wizji) i zakres stron (`PagesEditor` z `config/fields.tsx`), startowo
 * z `parser_config` dokumentu. Zapis oddaje `onSave(method, parserConfig)`, gdzie `parserConfig`
 * to konfiguracja dokumentu scalona z `layout_recognize` i `pages`; PATCH wysyła `useFileActions`.
 * Zmiana metody wymaga ponownego sparsowania — stąd ostrzeżenie.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import { modelsListQueryOptions } from '../../chats/modelsQuery'
import { CHUNK_METHODS } from '../queries'
import type { ChunkMethod } from '../queries'
import { PagesEditor } from '../config/fields'
import { LAYOUT_OPTIONS, LAYOUT_VALUES, visionModelNames } from '../config/schema'
import type { PageRange } from '../config/schema'
import { isCompleteRange } from '../config/schema'

export type ChunkMethodDialogProps = {
  open: boolean
  method: string
  /** `parser_config` dokumentu — źródło startowych wartości parsera i zakresu stron (§3). */
  parserConfig: Record<string, unknown>
  onSave: (method: ChunkMethod, parserConfig: Record<string, unknown>) => void
  onClose: () => void
  pending?: boolean
}

/** Wartość spoza `CHUNK_METHODS` spada na pierwszą metodę z listy (jak w `config/schema.ts`). */
function normalizeMethod(value: string): ChunkMethod {
  return CHUNK_METHODS.find((method) => method === value) ?? CHUNK_METHODS[0]
}

/** Parser dokumentu; brak klucza = domyślny `DeepDOC` (wzór `datasetToValues`). */
function layoutOf(parserConfig: Record<string, unknown>): string {
  const value = parserConfig.layout_recognize
  return typeof value === 'string' && value !== '' ? value : 'DeepDOC'
}

/** `parser_config.pages` → zakresy formularza; wpisy niepoprawne kształtem pomijamy. */
function pagesOf(value: unknown): PageRange[] {
  if (!Array.isArray(value)) return []
  const pages: PageRange[] = []
  for (const entry of value) {
    if (!Array.isArray(entry)) continue
    const [from, to] = entry
    if (typeof from === 'number' && typeof to === 'number') pages.push([from, to])
  }
  return pages
}

export function ChunkMethodDialog(props: ChunkMethodDialogProps): JSX.Element {
  const { open, method, parserConfig, onSave, onClose, pending } = props
  const { t } = useTranslation()
  const models = useQuery(modelsListQueryOptions())
  const [value, setValue] = useState<ChunkMethod>(() => normalizeMethod(method))
  const [layout, setLayout] = useState<string>(() => layoutOf(parserConfig))
  const [pages, setPages] = useState<PageRange[]>(() => pagesOf(parserConfig.pages))

  // „Reset przy otwarciu” wzorem Reacta: korekta stanu w renderze przy zmianie wartości propa
  // (efekt ze `setState` odrzuca lint: `react-hooks/set-state-in-effect`).
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open) {
      setValue(normalizeMethod(method))
      setLayout(layoutOf(parserConfig))
      setPages(pagesOf(parserConfig.pages))
    }
  }

  // Opcje jak w konfiguracji datasetu; bieżąca wartość pliku, gdy jej w nich nie ma, trafia na
  // początek, żeby dialog zawsze pokazywał faktyczną konfigurację (kontrakt §3).
  const visionNames = visionModelNames(models.data ?? [])
  const layoutChoices = [...LAYOUT_VALUES, ...visionNames]
  const layoutOptions = layoutChoices.includes(layout) ? layoutChoices : [layout, ...layoutChoices]

  // Półpełny wiersz zakresu (tylko „Od” albo tylko „Do”) blokuje zapis z komunikatem —
  // inaczej cichy zapis wyrzuciłby wpisaną wartość (SC-E5-H9-05: brak ukrytej zmiany).
  const incompleteRange = pages.some((range) => (range[0] === null) !== (range[1] === null))

  const save = (): void => {
    // Wiersz całkiem pusty pomijamy (SC-E5-H9-05) — bez ukrytego „1-1”.
    onSave(value, {
      ...parserConfig,
      layout_recognize: layout,
      pages: pages.filter(isCompleteRange),
    })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('datasets.files.method.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="warning">{t('datasets.files.method.warning')}</Alert>
          <TextField
            select
            fullWidth
            margin="dense"
            data-testid="method-select"
            label={t('datasets.files.col.method')}
            value={value}
            onChange={(event) => setValue(normalizeMethod(event.target.value))}
          >
            {CHUNK_METHODS.map((option) => (
              <MenuItem key={option} value={option}>
                {t(`datasets.method.${option}`)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            fullWidth
            margin="dense"
            data-testid="doc-pdf-parser-select"
            label={t('datasets.config.layoutRecognize')}
            value={layout}
            onChange={(event) => setLayout(event.target.value)}
          >
            {layoutOptions.map((option) => {
              const known = LAYOUT_OPTIONS.find((item) => item.value === option)
              return (
                <MenuItem key={option} value={option}>
                  {known === undefined ? option : t(known.labelKey)}
                </MenuItem>
              )
            })}
          </TextField>
          <PagesEditor
            pages={pages}
            error={incompleteRange ? t('datasets.config.pages.errorIncomplete') : null}
            onChange={setPages}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button
          data-testid="method-save"
          variant="contained"
          loading={pending}
          disabled={incompleteRange}
          onClick={save}
        >
          {t('datasets.files.method.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
