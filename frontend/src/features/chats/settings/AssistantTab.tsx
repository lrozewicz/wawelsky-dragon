/**
 * Zakładka „Asystent” szuflady ustawień czatu (08 §8.2): nazwa, opis, bazy wiedzy,
 * powitanie, odpowiedź przy braku wyników i cytowania; „Analiza słów kluczowych” (ADV)
 * siedzi w zwiniętym akordeonie.
 */

import { useEffect, useRef } from 'react'
import type { Ref } from 'react'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Autocomplete from '@mui/material/Autocomplete'
import FormControlLabel from '@mui/material/FormControlLabel'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { MetadataConditionBuilder } from '../../metadata/MetadataConditionBuilder'
import type { DatasetListItem } from '../datasetsQuery'
import type { ChatSettingsUpdate, ChatSettingsValues } from './schema'

export type AssistantTabProps = {
  values: ChatSettingsValues
  datasets: DatasetListItem[]
  /** Klucz i18n błędu nazwy (albo `null`, gdy poprawna). */
  nameError: string | null
  /** Klucz i18n błędu warunku filtra bez klucza (albo `null`) — komunikat przy polu (T6 c). */
  metaFilterKeyError?: string | null
  /** Klucz i18n błędu pustej wartości warunku (albo `null`) — pokazywany po próbie zapisu (SC-E67-06 k4). */
  metaFilterValueError?: string | null
  /** Otwarcie od chipa filtra: „Zaawansowane” i „Filtr metadanych” rozwinięte i przewinięte do widoku. */
  focusFilter?: boolean
  /** Ref pola nazwy — fokus przy próbie zapisu z błędem (U11). */
  nameInputRef?: Ref<HTMLInputElement>
  onUpdate: ChatSettingsUpdate
}

/** Pola bazy potrzebne do wyboru; `embedding_model` pusty = baza spoza pobranej listy. */
export type DatasetOption = Pick<DatasetListItem, 'id' | 'name' | 'embedding_model' | 'chunk_count'>

/** Wspólny powód wyłączenia bazy na liście wyboru (CONTRACT WP V13-2 §4, używa też okno
 *  „Nowy czat”): zero przetworzonych plików albo inny model embeddingu niż pierwsza wybrana
 *  baza o znanym modelu (`referenceEmbedding`; `undefined`, gdy nic jeszcze nie wybrano). */
export function datasetDisabledReason(
  dataset: DatasetOption,
  referenceEmbedding: string | undefined,
  t: TFunction,
): string | null {
  if (dataset.chunk_count === 0) return t('chat.settings.datasetsDisabledEmpty')
  if (
    dataset.embedding_model !== '' &&
    referenceEmbedding !== undefined &&
    dataset.embedding_model !== referenceEmbedding
  ) {
    return t('chat.settings.datasetsDisabledEmbedding')
  }
  return null
}

export function AssistantTab(props: AssistantTabProps) {
  const { values, datasets, nameError, focusFilter = false, onUpdate } = props
  const { t } = useTranslation()
  // Sekcja filtra przewijana do widoku: przy otwarciu od chipa (mount) i po rozwinięciu przez
  // użytkownika (po animacji — wcześniej treść jest za niska, by przewinąć do początku sekcji).
  const filterRef = useRef<HTMLDivElement>(null)
  // Przewija tylko najbliższy przewijalny kontener — `scrollIntoView` ruszałby też poziomo
  // okno szuflady, która w trakcie wsuwania jest jeszcze poza ekranem.
  const scrollToFilter = (): void => {
    const section = filterRef.current
    let box = section?.parentElement ?? null
    while (box !== null && getComputedStyle(box).overflowY !== 'auto') box = box.parentElement
    if (section && box) {
      box.scrollTop += section.getBoundingClientRect().top - box.getBoundingClientRect().top
    }
  }
  useEffect(() => {
    if (focusFilter) scrollToFilter()
  }, [focusFilter])
  // Bazy czatu spoza pobranej listy (błąd `GET /datasets`, usunięta baza, udostępniony czat bez
  // grantu na bazę — SC-V12-z-D3) zostają widoczne i usuwalne jako pozycje z czytelną etykietą
  // zamiast surowego id — inaczej wypadłyby z zapisu po cichu.
  const options: DatasetOption[] = [...datasets]
  const known = new Set(datasets.map((dataset) => dataset.id))
  for (const id of values.dataset_ids) {
    if (!known.has(id)) {
      options.push({
        id,
        name: t('common.kbUnavailable', { id: id.slice(-6) }),
        embedding_model: '',
        chunk_count: 1,
      })
    }
  }
  const selected = options.filter((dataset) => values.dataset_ids.includes(dataset.id))
  // Wzorzec modelu embeddingu to pierwsza wybrana baza o znanym modelu (08 §8.2).
  const referenceEmbedding = selected.find(
    (dataset) => dataset.embedding_model !== '',
  )?.embedding_model
  const disabledReason = (dataset: DatasetOption): string | null =>
    datasetDisabledReason(dataset, referenceEmbedding, t)

  return (
    <Stack spacing={2}>
      <TextField
        required
        fullWidth
        label={t('chat.settings.name')}
        value={values.name}
        inputRef={props.nameInputRef}
        error={nameError !== null}
        helperText={nameError !== null ? t(nameError) : undefined}
        onChange={(event) => onUpdate({ name: event.target.value })}
      />
      <TextField
        fullWidth
        multiline
        minRows={2}
        label={t('chat.settings.description')}
        value={values.description}
        onChange={(event) => onUpdate({ description: event.target.value })}
      />
      <Autocomplete
        multiple
        // Motyw daje OutlinedInput stałą wysokość — chip z długą nazwą bazy zawija pole wpisu
        // i wypychałoby je na następne pole („Powitanie”); wysokość rośnie z zawartością.
        sx={{ '& .MuiOutlinedInput-root': { height: 'auto', minHeight: '2.5rem' } }}
        options={options}
        value={selected}
        isOptionEqualToValue={(option, value) => option.id === value.id}
        getOptionLabel={(option) => option.name}
        getOptionDisabled={(option) => disabledReason(option) !== null}
        noOptionsText={t('chat.settings.noDatasets')}
        onChange={(_event, next) => onUpdate({ dataset_ids: next.map((dataset) => dataset.id) })}
        renderOption={(props, option) => {
          const { key, ...optionProps } = props
          const reason = disabledReason(option)
          if (reason === null) {
            return (
              <li key={key} {...optionProps}>
                {option.name}
              </li>
            )
          }
          // Wyszarzona opcja MUI ma `pointer-events: none`, co odcina też Tooltip; własny,
          // pełnowierszowy span przywraca najazd, a `stopPropagation` nie pozwala jej wybrać.
          return (
            <li key={key} {...optionProps}>
              <Tooltip title={reason}>
                <span
                  style={{ pointerEvents: 'auto', flex: 1 }}
                  onClick={(event) => event.stopPropagation()}
                >
                  {option.name}
                </span>
              </Tooltip>
            </li>
          )
        }}
        renderInput={(params) => <TextField {...params} label={t('chat.settings.datasets')} />}
      />
      <TextField
        fullWidth
        multiline
        minRows={2}
        label={t('chat.settings.prologue')}
        value={values.prompt_config.prologue}
        onChange={(event) =>
          onUpdate({
            prompt_config: { ...values.prompt_config, prologue: event.target.value },
          })
        }
      />
      <TextField
        fullWidth
        multiline
        minRows={2}
        label={t('chat.settings.emptyResponse')}
        value={values.prompt_config.empty_response}
        onChange={(event) =>
          onUpdate({
            prompt_config: { ...values.prompt_config, empty_response: event.target.value },
          })
        }
      />
      <FormControlLabel
        control={
          <Switch
            checked={values.prompt_config.quote}
            onChange={(event) =>
              onUpdate({
                prompt_config: { ...values.prompt_config, quote: event.target.checked },
              })
            }
          />
        }
        label={t('chat.settings.quote')}
      />

      <Accordion defaultExpanded={focusFilter}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>{t('chat.settings.advanced')}</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <FormControlLabel
            control={
              <Switch
                checked={values.prompt_config.keyword}
                onChange={(event) =>
                  onUpdate({
                    prompt_config: { ...values.prompt_config, keyword: event.target.checked },
                  })
                }
              />
            }
            label={t('chat.settings.keyword')}
          />
          {/* Filtr metadanych (E6-1b): kreator zapisuje się razem z resztą formularza
              (PATCH meta_data_filter); klucze czytane z wybranych baz, link prowadzi
              do konfiguracji pierwszej z nich (SC-E6-1b-05 krok 7). */}
          <Accordion
            ref={filterRef}
            defaultExpanded={focusFilter}
            slotProps={{ transition: { onEntered: scrollToFilter } }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>{t('metadata.filter.title')}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <MetadataConditionBuilder
                value={values.metaDataFilter}
                onChange={(metaDataFilter) => onUpdate({ metaDataFilter })}
                datasetIds={values.dataset_ids}
                modes={['off', 'manual', 'auto', 'semi_auto']}
                datasetConfigLinkId={values.dataset_ids[0]}
                // Warunek ręczny bez klucza (T6 c): komunikat z walidacji formularza przy polu.
                keyError={props.metaFilterKeyError == null ? null : t(props.metaFilterKeyError)}
                valueError={
                  props.metaFilterValueError == null ? null : t(props.metaFilterValueError)
                }
              />
            </AccordionDetails>
          </Accordion>
        </AccordionDetails>
      </Accordion>
    </Stack>
  )
}
