/**
 * Kreator warunków metadanych (kontrakt WP E6-1b §3, spec 08 §7.14 c) — komponent wspólny
 * filtra listy dokumentów (T5b) i `meta_data_filter` czatu/Search/retrievalu (T6).
 * Kontrolowany: nie zapisuje sam — każda zmiana idzie przez `onChange`, a warunki trybu
 * ręcznego, klucze półautomatyczne i podpowiedź trybu automatycznego zależą od `value`.
 */
import { useEffect, useRef } from 'react'
import Button from '@mui/material/Button'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import Radio from '@mui/material/Radio'
import RadioGroup from '@mui/material/RadioGroup'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { Link as RouterLink } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { useMetaKeys } from './queries'
import { ChipListInput } from './ChipListInput'
import { ConditionRow, convertConditionValue } from './ConditionRow'
import type { MetaCondition, MetaFilter, MetaFilterMethod } from './types'

export type MetadataConditionBuilderProps = {
  /** Bieżący stan filtra (kontrakt §2); kreator nie trzyma własnego stanu. */
  value: MetaFilter
  onChange: (value: MetaFilter) => void
  /** Bazy, z których czytane są klucze i znane wartości (`useMetaKeys`). */
  datasetIds: string[]
  /** Dostępne tryby; gdy jeden — bez przełącznika, od razu treść trybu (kontrakt §3). */
  modes: MetaFilterMethod[]
  /** Identyfikator datasetu dla linku stanu braku metadanych (kontrakt §4). */
  datasetConfigLinkId?: string
  disabled?: boolean
  /**
   * Komunikat walidacji warunku bez klucza (T6 c) — helperText przy polu „Klucz” każdego
   * pustego wiersza; już przetłumaczony (adapter formularza bierze go z błędu zod).
   */
  keyError?: string | null
  /** Komunikat walidacji pustej wartości warunku (SC-E67-06 k4) — helperText przy polu „Wartość”. */
  valueError?: string | null
  /** Podpis wyjaśniający wygaszone tryby (spoza `modes`), widoczny pod przełącznikiem (SC-E67-06 k6). */
  disabledModeHint?: string
}

const MODE_LABEL_KEYS: Record<MetaFilterMethod, string> = {
  off: 'metadata.builder.mode.off',
  manual: 'metadata.builder.mode.manual',
  auto: 'metadata.builder.mode.auto',
  semi_auto: 'metadata.builder.mode.semi_auto',
}

/** Wszystkie tryby — radiomy spoza `modes` są widoczne, ale nieaktywne (kontrakt §4: „niedostępne”). */
const ALL_MODES: readonly MetaFilterMethod[] = ['off', 'manual', 'auto', 'semi_auto']

export function MetadataConditionBuilder(props: MetadataConditionBuilderProps) {
  const {
    value,
    onChange,
    datasetIds,
    modes,
    datasetConfigLinkId,
    disabled = false,
    keyError = null,
    valueError = null,
    disabledModeHint,
  } = props
  const { t } = useTranslation()
  const { keys, hasAny, isLoading } = useMetaKeys(datasetIds)
  const knownKeys = Object.keys(keys)
  // Podpowiedź trybu „Automatyczny” bywa pod dolną krawędzią przewijanej szuflady (SC-E67-06 k7):
  // po zmianie trybu dosuwamy ją do widoku (`nearest` — bez ruchu, gdy już widać).
  const autoHintRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (value.method === 'auto') autoHintRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [value.method])

  const showModeSwitcher = modes.length > 1
  // Komunikat widoczny niezależnie od trybu (SC-E6-1b-05 krok 7: świeży czat ma „Wyłączony”,
  // a użytkownik ma się dowiedzieć, że filtr na tych bazach nie zadziała).
  const showNoMetadata = !isLoading && !hasAny

  const replaceCondition = (index: number, patch: Partial<MetaCondition>) =>
    onChange({
      ...value,
      manual: value.manual.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    })
  const removeCondition = (index: number) =>
    onChange({ ...value, manual: value.manual.filter((_, i) => i !== index) })
  const addCondition = () =>
    onChange({
      ...value,
      manual: [...value.manual, { key: knownKeys[0] ?? '', op: '=', value: '' }],
    })

  return (
    <Stack spacing={2}>
      {showModeSwitcher ? (
        <RadioGroup
          row
          aria-label={t('metadata.builder.mode.group')}
          value={value.method}
          onChange={(event) => {
            const method = event.target.value as MetaFilterMethod
            // Przejście w „Ręczny” od razu daje pierwszy (pusty) wiersz warunku — filtr ręczny
            // bez wiersza to ślepy zaułek (SC-E6-1b-05/06/07: „Warunek 1” czeka zaraz po wyborze).
            // Na bazie BEZ metadanych (hasAny=false) edytor warunków jest ukryty (SC-05 krok 7),
            // a warunek z pustym kluczem wysłany do backendu dałby 400 przy każdym pytaniu —
            // zostaje `manual: []` (brak zawężenia, zachowanie jak w T3).
            const manual =
              method === 'manual' && value.manual.length === 0 && hasAny
                ? [{ key: knownKeys[0] ?? '', op: '=' as const, value: '' }]
                : value.manual
            onChange({ ...value, method, manual })
          }}
        >
          {ALL_MODES.map((mode) => (
            <FormControlLabel
              key={mode}
              value={mode}
              control={<Radio disabled={disabled || !modes.includes(mode)} />}
              label={t(MODE_LABEL_KEYS[mode])}
              disabled={disabled || !modes.includes(mode)}
            />
          ))}
        </RadioGroup>
      ) : null}

      {/*
        M3 (WP V12-2 C.5): krótki opis aktualnego trybu — sama lista „Wyłączony/Ręczny/…”
        nie mówi, co tryb robi (QA E67-z2-2). Tekst pomocniczy zamiast tooltipu: widać bez
        najechania, także na dotyku; podąża za wyborem w przełączniku, a przy pojedynczym
        trybie (filtr listy plików) wyjaśnia ten jedyny.
      */}
      <Typography variant="caption" color="text.secondary" data-testid="metadata-mode-desc">
        {t(`metadata.builder.modeDesc.${value.method}`)}
      </Typography>

      {showModeSwitcher && disabledModeHint !== undefined && modes.length < ALL_MODES.length ? (
        // Podpis zamiast samego tooltipu: wyjaśnienie widać bez najechania (także na dotyku).
        <Typography variant="caption" color="text.secondary">
          {disabledModeHint}
        </Typography>
      ) : null}

      {showNoMetadata ? (
        <Typography variant="body2">
          {datasetConfigLinkId !== undefined ? (
            <>
              {t('metadata.builder.empty.text')}{' '}
              <RouterLink
                to="/dataset/configuration/$id"
                params={{ id: datasetConfigLinkId }}
                style={{ color: 'inherit' }}
              >
                {t('metadata.builder.empty.link')}
              </RouterLink>
            </>
          ) : (
            // Bez wybranej bazy nie ma dokąd linkować — pełne zdanie zamiast urwanego na „w”.
            t('metadata.builder.empty.textNoLink')
          )}
        </Typography>
      ) : null}

      {!showNoMetadata && value.method === 'manual' ? (
        <Stack spacing={1}>
          <Stack direction="row" sx={{ alignItems: 'center', flexWrap: 'nowrap', gap: 1 }}>
            <Typography variant="body2" sx={{ whiteSpace: 'nowrap' }}>
              {t('metadata.builder.logic.prefix')}
            </Typography>
            <TextField
              select
              size="small"
              disabled={disabled}
              value={value.logic}
              onChange={(event) =>
                onChange({ ...value, logic: event.target.value === 'or' ? 'or' : 'and' })
              }
              slotProps={{ htmlInput: { 'aria-label': t('metadata.builder.logic.label') } }}
              sx={{
                // Kurczy się w wąskiej szufladzie (390 px), żeby „warunki” nie spadało do nowej linii
                // (wiersz bez zawijania — zawijanie liczyłoby się od bazowych 150 px).
                flex: '0 1 150px',
                minWidth: 0,
                '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis' },
              }}
            >
              <MenuItem value="and">{t('metadata.builder.logic.and')}</MenuItem>
              <MenuItem value="or">{t('metadata.builder.logic.or')}</MenuItem>
            </TextField>
            <Typography variant="body2" sx={{ whiteSpace: 'nowrap' }}>
              {t('metadata.builder.logic.suffix')}
            </Typography>
          </Stack>

          {value.manual.map((condition, index) => (
            <ConditionRow
              key={index}
              index={index + 1}
              condition={condition}
              keys={keys}
              disabled={disabled}
              keyError={keyError}
              valueError={valueError}
              onKeyChange={(key) => replaceCondition(index, { key })}
              onOpChange={(op) =>
                replaceCondition(index, { op, value: convertConditionValue(condition.value, op) })
              }
              onValueChange={(val) => replaceCondition(index, { value: val })}
              onRemove={() => removeCondition(index)}
            />
          ))}

          <Button
            size="small"
            variant="outlined"
            disabled={disabled}
            onClick={addCondition}
            sx={{ alignSelf: 'flex-start' }}
          >
            {t('metadata.builder.condition.add')}
          </Button>
        </Stack>
      ) : null}

      {!showNoMetadata && value.method === 'auto' ? (
        <Typography ref={autoHintRef} variant="body2">
          {t('metadata.builder.auto.hint')}
        </Typography>
      ) : null}

      {!showNoMetadata && value.method === 'semi_auto' ? (
        <Stack spacing={0.5}>
          <Typography variant="body2">{t('metadata.builder.semi.label')}</Typography>
          <ChipListInput
            value={value.semi_auto}
            onChange={(semi_auto) => onChange({ ...value, semi_auto })}
            options={knownKeys}
            inputLabel={t('metadata.builder.semi.add')}
            removeLabel={(key) => t('metadata.builder.semi.remove', { key })}
            disabled={disabled}
          />
        </Stack>
      ) : null}
    </Stack>
  )
}
