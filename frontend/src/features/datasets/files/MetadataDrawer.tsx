/**
 * Szuflada edycji metadanych dokumentu (kontrakt WP E6-1b §4, spec 08 §7.14 b): `Drawer
 * anchor="right"` szerokości 390 px (pełna szerokość na wąskim ekranie), tytuł = nazwa pliku
 * z wielokropkiem. Tabela klucz/wartość z edycją inline: „+ Pole” (fokus w „Klucz”), „Usuń pole”,
 * „Zapisz”, „Anuluj”; wartość-lista edytuje się edytorem chipów (`ChipListInput`, T3).
 * Wartości nietknięte zachowują oryginalny typ (`metaToRows`/`rowsToMeta`, T2).
 * „Zapisz” woła `patchDocumentMeta` (PATCH `…/documents/{id}` z całym `meta_fields`), po sukcesie
 * unieważnia listę i podsumowanie kluczy, pokazuje toast, zamyka szufladę, a fokus wraca na ⋮
 * wiersza (przywraca go `FocusTrap` MUI — przed otwarciem szuflady fokus leżał na ⋮). Bez zmian
 * „Zapisz” jest nieaktywny z powodem „Brak zmian do zapisania” (SC-V13-11). Błąd zapisu
 * ląduje w alercie szuflady, wpisane wartości zostają. Zamknięcie przy niezapisanych zmianach
 * (Esc, tło, „Anuluj”, ✕) pyta „Odrzucić zmiany?” — wspólny `useDiscardGuard` (SC-V12-07).
 *
 * Zamknięcie szuflady odmontowuje formularz, więc stan startuje na nowo przy każdym otwarciu,
 * bez efektów i bez gubienia niezapisanych zmian przy refetchu (wzorzec: `ChatSettingsDrawer`).
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import CloseIcon from '@mui/icons-material/Close'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { useDiscardGuard } from '../../../components/useDiscardGuard'
import { DisabledReason, describedBy } from '../../../components/DisabledReason'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { ChipListInput } from '../../metadata/ChipListInput'
import { metaToRows, rowsToMeta } from '../../metadata/convert'
import type { MetaRow } from '../../metadata/convert'
import { metadataKeys, patchDocumentMeta } from '../../metadata/queries'
import { mutationMessage } from '../config/helpers'
import { documentKeys } from './queries'
import type { DocumentRow } from './queries'

export type MetadataDrawerProps = {
  open: boolean
  datasetId: string
  /** Dokument otwarty z listy (zrzut z chwili kliknięcia); `null` = szuflada zamknięta. */
  doc: Pick<DocumentRow, 'id' | 'name' | 'meta_fields'> | null
  onClose: () => void
}

/** Formularz wierszy — remontowany per otwarcie (`key` na dokumencie), czysty od stanu zapisu. */
function MetadataForm(props: {
  datasetId: string
  doc: NonNullable<MetadataDrawerProps['doc']>
  /** Bezpośrednie zamknięcie po udanym zapisie — bez pytania o odrzucenie (SC-V12-07). */
  onClose: () => void
  /** „Anuluj” — przez strażnika: przy zmianach pyta „Odrzucić zmiany?”. */
  onCancel: () => void
  /** Podniesienie faktu „brudny” do szuflady (strażnik pilnuje Esc/tła/✕ w nagłówku). */
  onDirtyChange: (dirty: boolean) => void
}) {
  const { datasetId, doc, onClose, onCancel, onDirtyChange } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const queryClient = useQueryClient()

  const [rows, setRows] = useState<MetaRow[]>(() => metaToRows(doc.meta_fields))
  // „Brudny” = wartości formularza ≠ stan początkowy (SC-V12-07); proste dane — porównanie
  // przez JSON (wzorzec: `SearchSettingsDrawer`).
  const [initialRows] = useState<MetaRow[]>(() => metaToRows(doc.meta_fields))
  const dirty = JSON.stringify(rows) !== JSON.stringify(initialRows)
  // Powód nieaktywnego „Zapisz” (SC-V13-11): jedyną przyczyną jest brak zmian (DEC-372).
  const saveReason = dirty ? null : t('common.noChangesToSave')

  // Strażnik zamknięcia żyje w szufladzie (Esc/tło/✕ w nagłówku) — podnosimy stan „brudny”.
  useEffect(() => {
    onDirtyChange(dirty)
  }, [dirty, onDirtyChange])
  const [error, setError] = useState<string | null>(null)
  // Duplikaty klucza (po trim): `rowsToMeta` zachowuje ostatni z powtórzonych — użytkownik
  // dostaje komunikat przy polu powtórzonego wiersza (T5a/T3 MINOR), wartości zostają.
  const seenKeys = new Set<string>()
  const duplicateRows = rows.map((row) => {
    const key = row.key.trim()
    const duplicate = key !== '' && seenKeys.has(key)
    seenKeys.add(key)
    return duplicate
  })
  // „+ Pole” dostaje fokus w „Klucz” nowego wiersza (kontrakt §4): indeks czeka w referencji,
  // efekt po commit wiąże go z inputem zmapowanym per wiersz.
  const keyInputs = useRef<Array<HTMLInputElement | null>>([])
  const pendingFocus = useRef<number | null>(null)
  // Kotwica fokusu dla usuwania wierszy (przycisk trwa przy zmianach listy).
  const addFieldRef = useRef<HTMLButtonElement>(null)

  const save = useMutation({
    mutationFn: () => patchDocumentMeta(datasetId, doc.id, rowsToMeta(rows)),
    onSuccess: () => {
      // Unieważnienie listy (kolumna odświeża się bez ręcznego F5) i podsumowania kluczy,
      // z którego kreator filtra bierze podpowiedzi (kontrakt WP E6-1b §4).
      void queryClient.invalidateQueries({ queryKey: documentKeys.all(datasetId) })
      void queryClient.invalidateQueries({ queryKey: metadataKeys.summary(datasetId) })
      show(t('metadata.drawer.saved'), { severity: 'success', autoHideDuration: 4000 })
      onClose()
    },
    // Błąd zapisu (T3b): komunikat serwera tłumaczony wg INVENTORY, transport — generyk.
    onError: (failure) => setError(mutationMessage(failure, t('metadata.drawer.saveError'), t)),
  })

  useEffect(() => {
    if (pendingFocus.current === null) return
    keyInputs.current[pendingFocus.current]?.focus()
    pendingFocus.current = null
  }, [rows])

  function addRow(): void {
    // `untouched: ''` (tekst) — nowy wiersz nigdy nie dziedziczy typu starej wartości (T2).
    pendingFocus.current = rows.length
    setRows((prev) => [...prev, { key: '', value: '', untouched: '' }])
  }

  function updateRow(index: number, next: Partial<MetaRow>): void {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...next } : row)))
  }

  function removeRow(index: number): void {
    // Fokus wraca na „+ Pole” — inaczej wypada z formularza (usunięty przycisk ⋮), a Escape
    // w szufladzie przestaje działać (SC-V13-11 k3: cofnięcie zmiany klawiaturą zamyka Escapem).
    addFieldRef.current?.focus()
    setRows((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <>
      {error !== null ? (
        <Alert severity="error" sx={{ mx: 2, mt: 1 }}>
          {error}
        </Alert>
      ) : null}
      <Box sx={{ p: 2, flex: 1, overflowY: 'auto' }}>
        <Stack spacing={2}>
          <Button ref={addFieldRef} onClick={addRow}>
            {t('metadata.drawer.addField')}
          </Button>
          {rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('metadata.drawer.empty')}
            </Typography>
          ) : (
            rows.map((row, index) => (
              <Stack key={index} direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                <TextField
                  size="small"
                  label={t('metadata.drawer.key')}
                  error={duplicateRows[index]}
                  helperText={duplicateRows[index] ? t('metadata.drawer.keyDuplicate') : undefined}
                  slotProps={{
                    htmlInput: { 'aria-label': t('metadata.drawer.key'), title: row.key },
                  }}
                  value={row.key}
                  onChange={(event) => updateRow(index, { key: event.target.value })}
                  // Ref per wiersz — „+ Pole” przenosi fokus do „Klucz” nowego wiersza (kontrakt §4).
                  inputRef={(el) => {
                    keyInputs.current[index] = el
                  }}
                  // Długi klucz kończy się wielokropkiem, pełny w `title` (T8).
                  sx={{ width: 132, flexShrink: 0, '& input': { textOverflow: 'ellipsis' } }}
                />
                {Array.isArray(row.value) ? (
                  <ChipListInput
                    value={row.value}
                    onChange={(next) => updateRow(index, { value: next })}
                    inputLabel={t('metadata.drawer.value')}
                    label={t('metadata.drawer.value')}
                    removeLabel={(chip) => t('metadata.builder.value.remove', { value: chip })}
                  />
                ) : (
                  // Długa wartość zawija się w szufladzie (kontrakt §4, SC-E6-1b-03 krok 4).
                  <TextField
                    size="small"
                    label={t('metadata.drawer.value')}
                    multiline
                    minRows={1}
                    maxRows={4}
                    slotProps={{ htmlInput: { 'aria-label': t('metadata.drawer.value') } }}
                    value={row.value}
                    onChange={(event) => updateRow(index, { value: event.target.value })}
                    sx={{ flex: 1, minWidth: 0 }}
                  />
                )}
                <IconButton
                  size="small"
                  aria-label={t('metadata.drawer.removeField')}
                  onClick={() => removeRow(index)}
                >
                  <DeleteOutlineRoundedIcon />
                </IconButton>
              </Stack>
            ))
          )}
        </Stack>
      </Box>
      <Stack
        direction="row"
        spacing={1}
        sx={{
          p: 2,
          justifyContent: 'flex-end',
          flexWrap: 'wrap',
          rowGap: 0.5,
          borderTop: 1,
          borderColor: 'divider',
        }}
      >
        <DisabledReason id="metadata-save-reason" reason={saveReason} />
        <Button onClick={onCancel}>{t('common.cancel')}</Button>
        <Button
          variant="contained"
          disabled={!dirty}
          loading={save.isPending}
          onClick={() => save.mutate()}
          aria-describedby={describedBy('metadata-save-reason', saveReason)}
        >
          {t('metadata.drawer.save')}
        </Button>
      </Stack>
    </>
  )
}

export function MetadataDrawer(props: MetadataDrawerProps): JSX.Element {
  const { open, datasetId, doc, onClose } = props
  const { t } = useTranslation()

  // Strażnik niezapisanych zmian (SC-V12-07): Esc/tło/„Anuluj”/✕ przy brudnym formularzu pyta
  // „Odrzucić zmiany?”. Stan „brudny” podnosi formularz; zamknięcie szuflady zeruje go od razu
  // (korekta podczas renderu, wzorzec: `SearchSettingsDrawer`).
  const [dirty, setDirty] = useState(false)
  const [lastOpen, setLastOpen] = useState(open)
  if (lastOpen !== open) {
    setLastOpen(open)
    setDirty(false)
  }
  const { requestClose, dialog } = useDiscardGuard({ dirty, onClose, context: 'metadata', open })

  let content: ReactNode = null
  if (open && doc !== null) {
    content = (
      <MetadataForm
        key={doc.id}
        datasetId={datasetId}
        doc={doc}
        onClose={onClose}
        onCancel={requestClose}
        onDirtyChange={setDirty}
      />
    )
  }

  return (
    <>
      {/* min(…, 100vw) — szuflada mieści się w całości także na wąskim ekranie (R-UI-01); 390 px
          pełna szerokość okna (kontrakt WP E6-1b §4, test SC-E6-1b-03 wariant 390 px).
          Bez animacji wejścia (`transitionDuration={0}`): strażnik układu i test 390 px mierzą
          geometrię tuż po `toBeVisible`, a slajd MUI w tym momencie jeszcze trwa i daje wadę
          `off-screen` (MINOR z T1 w s18: „tuż po `toBeVisible` slajd trwa”). */}
      <Drawer
        anchor="right"
        open={open}
        onClose={requestClose}
        transitionDuration={0}
        slotProps={{
          paper: {
            'aria-label': doc?.name,
            sx: { width: { xs: 'min(100%, 100vw)', sm: 'min(390px, 100vw)' } },
          },
        }}
      >
        <Stack sx={{ height: '100%' }}>
          {/* Nagłówek z ✕ (wzorzec: `ChatSettingsDrawer`); tytuł = nazwa pliku z wielokropkiem (U2),
              pełna nazwa w podpowiedzi. ✕ zamyka przez strażnika (przy zmianach pyta). */}
          <Stack
            direction="row"
            sx={{ p: 2, pb: 1, alignItems: 'center', justifyContent: 'space-between' }}
          >
            <Typography variant="h6" noWrap title={doc?.name} sx={{ minWidth: 0 }}>
              {doc?.name ?? ''}
            </Typography>
            <IconButton aria-label={t('common.close')} onClick={requestClose}>
              <CloseIcon />
            </IconButton>
          </Stack>
          {content}
        </Stack>
      </Drawer>
      {dialog}
    </>
  )
}
