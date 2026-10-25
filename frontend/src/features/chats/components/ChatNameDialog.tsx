/**
 * Okno nazwy czatu (08 §7.6): jedno dla tworzenia (`POST /chats`) i zmiany nazwy (`PATCH`).
 * Pole „Nazwa” jest wymagane (U11, kontrakt K2): przycisk zapisu pozostaje aktywny, a klik przy
 * pustej nazwie (po trim) pokazuje `common.required` pod polem i wraca fokusem do pola; etykieta
 * zostaje nad polem. Zmiana treści gasi komunikat. Błąd mutacji wraca tu jako `error` (Alert nad
 * polem). Wołający renderuje komponent tylko wtedy, gdy okno ma być widoczne — stan pola startuje
 * z `initialName` (U7: zamknięcie = czysty stan przy kolejnym otwarciu).
 * Tryb tworzenia (`showDatasets`, SC-V13-10 / CONTRACT WP V13-2 §4) dokłada pole „Bazy wiedzy
 * (opcjonalnie)”: Autocomplete multiple z tą samą listą i kryteriami wyłączenia co zakładka
 * „Asystent” (baza bez przetworzonych plików z widocznym dopiskiem w osobnym wierszu — makieta
 * wiążąca; inny model embeddingu), z tekstem pomocniczym; wybrane id wracają drugim argumentem
 * `onSubmit`. Wybór zamyka listę, a popup mieści się w oknie nad stopką z przyciskami
 * (QA V13-2-1 MAJOR-1).
 */

import * as React from 'react'
import { useRef, useState } from 'react'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { datasetsListQueryOptions } from '../datasetsQuery'
import { datasetDisabledReason } from '../settings/AssistantTab'
import type { DatasetOption } from '../settings/AssistantTab'

export type ChatNameDialogProps = {
  title: string
  submitLabel: string
  /** Wartość początkowa pola; przy tworzeniu pusta. */
  initialName?: string
  loading?: boolean
  /** Komunikat błędu mutacji (np. z `ApiError`) — `null`/brak ukrywa Alert. */
  error?: string | null
  /** Pole „Bazy wiedzy (opcjonalnie)” — tylko tryb tworzenia (SC-V13-10); zmiana nazwy bez baz. */
  showDatasets?: boolean
  onSubmit: (name: string, datasetIds: string[]) => void
  onClose: () => void
}

/** Wielokropek; pełna nazwa w dymku pochodzi z `title` na opcji (QA V13-z-2 D4). */
function optionName(option: DatasetOption, disabled: boolean): React.ReactNode {
  return (
    <span
      style={{
        // Własny wiersz pełnej szerokości (QA MINOR-2): wielokropek tylko dla naprawdę długich.
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        minWidth: 0,
        // Wyszarzona opcja MUI ma `pointer-events: none`; przywrócenie na nazwie podtrzymuje
        // najazd (dymek `title` z `li`), a `stopPropagation` nie pozwala jej wybrać (wzór: AssistantTab).
        pointerEvents: disabled ? 'auto' : undefined,
      }}
      onClick={disabled ? (event) => event.stopPropagation() : undefined}
    >
      {option.name}
    </span>
  )
}

export function ChatNameDialog(props: ChatNameDialogProps) {
  const { title, submitLabel, initialName = '', loading, error, onSubmit, onClose } = props
  const { t } = useTranslation()
  const [name, setName] = useState(initialName)
  // Walidacja U11: komunikat o pustym polu dopiero po próbie wysłania.
  const [invalid, setInvalid] = useState(false)
  const [datasetIds, setDatasetIds] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  // U7: drugi klik „Zapisz” wyściga re-render z `loading` (dblclick) i wysłałby mutację drugi
  // raz; blokada na refie działa synchronicznie, reset przy ustaniu `loading` (błąd → można
  // ponowić; sukces → okno i tak znika). Wymaga, by wołający przekazywał `loading` z mutacji.
  const submittingRef = useRef(false)
  React.useEffect(() => {
    if (loading !== true) submittingRef.current = false
  }, [loading])
  const showDatasets = props.showDatasets === true
  // Ten sam hook co zakładka „Asystent”; pobranie tylko w trybie tworzenia.
  const datasetsQuery = useQuery({ ...datasetsListQueryOptions(), enabled: showDatasets })
  const options: DatasetOption[] = datasetsQuery.data ?? []
  const selected = options.filter((dataset) => datasetIds.includes(dataset.id))
  // Wzorzec modelu embeddingu = pierwsza wybrana baza o znanym modelu (jak w AssistantTab).
  const referenceEmbedding = selected.find(
    (dataset) => dataset.embedding_model !== '',
  )?.embedding_model
  // Lista nie może nachodzić na stopkę (QA V13-2-1 MAJOR-1) ani przycinać opcji (QA W1): popup
  // idzie po wyższej stronie pola — w dół ogranicza go stopka, w górę okno; maksimum z viewportu
  // (min(40vh, 320px)), a `snapListbox` niżej zbija `max-height` do pełnych wierszy.
  const fieldBoxRef = useRef<HTMLDivElement>(null)
  const [popup, setPopup] = useState<{
    maxHeight: number
    placement: 'bottom-start' | 'top-start'
  }>({
    maxHeight: 320,
    placement: 'bottom-start',
  })
  const handlePopupOpen = () => {
    const fieldBox = fieldBoxRef.current
    const paper = fieldBox !== null ? fieldBox.closest('.MuiDialog-paper') : null
    const actions = paper?.querySelector('.MuiDialogActions-root') ?? null
    if (fieldBox === null || paper === null || actions === null) return
    const field = fieldBox.getBoundingClientRect()
    const margin = 12 // odstęp od krawędzi + offset poppera
    const cap = Math.min(320, Math.round(window.innerHeight * 0.4))
    const below = Math.min(
      Math.floor(actions.getBoundingClientRect().top - field.bottom - margin),
      cap,
    )
    const above = Math.min(Math.floor(field.top - margin), cap)
    setPopup(
      below >= above
        ? { maxHeight: below, placement: 'bottom-start' }
        : { maxHeight: above, placement: 'top-start' },
    )
  }
  // QA V13-z-1 W1: maksimum (np. 113 px) nie dzieli się na wysokości opcji — „GUS” był przycięty
  // w połowie. Ref listboxa zbijamy `max-height` do pełnych wierszy; pomiar `offsetHeight` nie
  // zależy od skali Grow, a zerowe wysokości (jsdom) zostawiają styl z `sx`.
  const snapListbox = React.useCallback(
    (node: HTMLUListElement | null) => {
      if (node === null) return
      const rows = Array.from(node.querySelectorAll<HTMLLIElement>(':scope > li'))
      if (rows.length === 0 || rows.every((row) => row.offsetHeight === 0)) return
      const padTop = parseFloat(getComputedStyle(node).paddingTop)
      const limit = popup.maxHeight - padTop
      let used = 0
      let visible = 0
      for (const row of rows) {
        const height = row.offsetHeight
        if (used + height > limit) break
        used += height
        visible += 1
      }
      // Wszystkie mieszczą się w całości albo brak miejsca na choć jedną — zostaw maksimum.
      if (visible === 0 || visible === rows.length) return
      node.style.maxHeight = `${padTop + used}px`
    },
    [popup.maxHeight],
  )

  const trimmed = name.trim()
  const isValid = trimmed !== ''
  const showError = invalid && !isValid

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      slotProps={{
        paper: {
          component: 'form',
          // Natywna walidacja przeglądarki blokowałaby `submit` przy pustym polu `required`,
          // zanim nasz komunikat w ogóle zdążyłby się pokazać (wzór: `ChunkDialog`).
          noValidate: true,
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            if (submittingRef.current) return
            if (isValid) {
              submittingRef.current = true
              onSubmit(trimmed, datasetIds)
              return
            }
            setInvalid(true)
            inputRef.current?.focus()
          },
        } as React.ComponentPropsWithRef<'form'>,
      }}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error !== null && error !== undefined ? <Alert severity="error">{error}</Alert> : null}
          <TextField
            autoFocus
            required
            fullWidth
            margin="dense"
            label={t('chats.name')}
            value={name}
            inputRef={inputRef}
            error={showError}
            helperText={showError ? t('common.required') : undefined}
            slotProps={{ inputLabel: { shrink: showError ? true : undefined } }}
            onChange={(event) => {
              setName(event.target.value)
              setInvalid(false)
            }}
          />
          {showDatasets ? (
            <>
              <Autocomplete
                multiple
                fullWidth
                ref={fieldBoxRef}
                // Wybór ZAMYKA listę (domyślne zachowanie MUI; QA MAJOR-1: `disableCloseOnSelect`
                // zostawiało listę otwartą nad przyciskami po wyborze bazy). Ponowne otwarcie
                // klikiem pola/strzałką.
                onOpen={handlePopupOpen}
                slotProps={{
                  popper: {
                    placement: popup.placement,
                    sx: { '& .MuiAutocomplete-listbox': { maxHeight: popup.maxHeight } },
                  },
                  listbox: { ref: snapListbox },
                }}
                // Motyw daje OutlinedInput stałą wysokość — chip z długą nazwą bazy zawija pole
                // wpisu zamiast rosnąć z zawartością (wzór: AssistantTab).
                sx={{ '& .MuiOutlinedInput-root': { height: 'auto', minHeight: '2.5rem' } }}
                options={options}
                value={selected}
                isOptionEqualToValue={(option, value) => option.id === value.id}
                getOptionLabel={(option) => option.name}
                getOptionDisabled={(option) =>
                  datasetDisabledReason(option, referenceEmbedding, t) !== null
                }
                noOptionsText={t('chat.settings.noDatasets')}
                loading={datasetsQuery.isPending}
                onChange={(_event, next) => setDatasetIds(next.map((dataset) => dataset.id))}
                // Pełna nazwa bazy w `title` chipa (U2); etykietę skraca styl Chip (wielokropek).
                renderValue={(value, getItemProps) =>
                  value.map((option, index) => {
                    const { key, ...itemProps } = getItemProps({ index })
                    return (
                      <Chip
                        key={key}
                        label={option.name}
                        title={option.name}
                        sx={{
                          maxWidth: '100%',
                          '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' },
                        }}
                        {...itemProps}
                      />
                    )
                  })
                }
                renderOption={(optionProps, option) => {
                  const { key, ...rest } = optionProps
                  const reason = datasetDisabledReason(option, referenceEmbedding, t)
                  return (
                    // Pełna nazwa w natywnym dymku opcji (QA V13-z-2 D4): wielokropek na nazwie
                    // nie może zjadać informacji — `title` reaguje na najazd na cały wiersz.
                    <li key={key} title={option.name} {...rest}>
                      {/* Dopisek w OSOBNYM wierszu pod nazwą (QA MINOR-2): nazwa ma pełną
                          szerokość wiersza; `flex: 1` rozciąga też przy li jako flex. */}
                      <Box sx={{ minWidth: 0, flex: 1 }}>
                        {optionName(option, reason !== null)}
                        {reason !== null ? (
                          // Dopisek przy wyszarzonej bazie jest widoczny na liście (makieta SC-V13-10).
                          <Typography variant="caption" color="text.secondary">
                            {reason}
                          </Typography>
                        ) : null}
                      </Box>
                    </li>
                  )
                }}
                renderInput={(params) => (
                  <TextField {...params} label={t('chats.datasetsOptional')} />
                )}
              />
              {/* Teksty pomocnicze (CONTRACT WP V13-2 §4). */}
              <Typography variant="body2" color="text.secondary">
                {t('chats.datasetsHintModel')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('chats.datasetsHintLater')}
              </Typography>
            </>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button type="submit" variant="contained" loading={loading}>
          {submitLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
