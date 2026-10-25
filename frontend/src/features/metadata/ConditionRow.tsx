/**
 * Wiersz warunku kreatora (kontrakt WP E6-1b §4): `role="group"` „Warunek <n>”, combobox klucza
 * z podpowiedziami metadanych i wpisem własnym, select operatora (14 operatorów) i wartość
 * zależna od operatora oraz znanych wartości klucza: combobox z wolnym wpisem (≤ 20, `=`/`≠`),
 * chipy (`in`/`not in`), pole tekstowe albo podpowiedź ⓘ (`empty`/`not empty`).
 * Desktop w jednej linii, < 600 px pod sobą (U1/U3).
 */
import Box from '@mui/material/Box'
import Autocomplete from '@mui/material/Autocomplete'
import IconButton from '@mui/material/IconButton'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useTranslation } from 'react-i18next'

import { ChipListInput } from './ChipListInput'
import { LIST_VALUE_OPS, META_OPS, NO_VALUE_OPS } from './types'
import type { MetaCondition, MetaOp } from './types'

/** Próg selecta znanych wartości (kontrakt §4: „klucz ma ≤ 20 znanych wartości”). */
const KNOWN_VALUES_LIMIT = 20

/** Wartość warunku po zmianie operatora: string ↔ lista ↔ `''` (brief T3). */
export function convertConditionValue(value: string | string[], op: MetaOp): string | string[] {
  if (NO_VALUE_OPS.includes(op)) return ''
  if (LIST_VALUE_OPS.includes(op)) {
    // `in` → `=` skleja listę do „a, b”; powrót do `in` rozdziela ją z powrotem (MINOR E6-1b T3a).
    if (typeof value === 'string') {
      return value
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item !== '')
    }
    return value
  }
  if (Array.isArray(value)) return value.join(', ')
  return value
}

export type ConditionRowProps = {
  /** Numer wiersza (1-based) dla aria-label grupy. */
  index: number
  condition: MetaCondition
  /** Znane klucze metadanych i ich wartości (`useMetaKeys`). */
  keys: Record<string, string[]>
  disabled: boolean
  /** Komunikat walidacji pustego klucza (T6 c) — helperText przy polu „Klucz”; już przetłumaczony. */
  keyError?: string | null
  /** Komunikat pustej wartości (SC-E67-06 k4) — helperText przy polu „Wartość”; już przetłumaczony. */
  valueError?: string | null
  onKeyChange: (key: string) => void
  onOpChange: (op: MetaOp) => void
  onValueChange: (value: string | string[]) => void
  onRemove: () => void
}

export function ConditionRow(props: ConditionRowProps) {
  const {
    index,
    condition,
    keys,
    disabled,
    keyError = null,
    valueError = null,
    onKeyChange,
    onOpChange,
    onValueChange,
    onRemove,
  } = props
  const { t } = useTranslation()
  const knownValues = keys[condition.key] ?? []
  const stringValue = Array.isArray(condition.value) ? condition.value.join(', ') : condition.value
  const isListOp = LIST_VALUE_OPS.includes(condition.op)
  const isNoValueOp = NO_VALUE_OPS.includes(condition.op)
  const keyEmpty = condition.key.trim() === ''
  const valueEmpty = Array.isArray(condition.value)
    ? condition.value.length === 0
    : condition.value.trim() === ''
  const showValueError = !isNoValueOp && valueEmpty && valueError !== null
  const hasFewKnownValues =
    condition.key.trim() !== '' &&
    knownValues.length > 0 &&
    knownValues.length <= KNOWN_VALUES_LIMIT &&
    (condition.op === '=' || condition.op === '≠')

  return (
    // Wrap zamiast breakpointów viewportu (U1, brief T6 „szuflady 390 px — kreator w kolumnie”):
    // w wąskim kontenerze (szuflada, popover) pola zawijają się pod siebie, w szerokim stoją
    // w jednej linii — liczy się szerokość KONTENERA, nie okna. W wąskim kontenerze (≤ 520 px)
    // układ to siatka 2 linii: „klucz + kosz” nad „operator + wartość” (SC-E67-z2-04; wcześniej 3 linie).
    <Box sx={{ containerType: 'inline-size' }}>
      <Stack
        role="group"
        aria-label={t('metadata.builder.condition.group', { index })}
        direction="row"
        // `gap` zamiast `spacing`: spacing dokłada margines tylko pierwszej kolumnie zawiniętych
        // wierszy (operator wcięty o 8 px). Do górnej linii, by kosz nie skakał po pojawieniu
        // się helperText pod polem wartości.
        sx={{
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: 1,
          '@container (max-width: 520px)': {
            display: 'grid',
            gridTemplateColumns: '150px minmax(0, 1fr) auto',
            gridTemplateAreas: '"key key trash" "op value value"',
          },
        }}
      >
        <Autocomplete
          autoSelect
          freeSolo
          openOnFocus
          disabled={disabled}
          options={Object.keys(keys)}
          value={condition.key === '' ? null : condition.key}
          onChange={(_event, next) => onKeyChange(typeof next === 'string' ? next : '')}
          sx={{ flex: '1 1 240px', minWidth: 0, gridArea: 'key' }}
          // Długi klucz na liście podpowiedzi kończy się wielokropkiem (T8, SC-E67-z2-26).
          slotProps={{
            listbox: {
              sx: {
                '& .MuiAutocomplete-option': {
                  display: 'block',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                },
              },
            },
          }}
          renderInput={(params) => (
            <TextField
              {...params}
              size="small"
              title={condition.key}
              placeholder={t('metadata.builder.condition.keyPlaceholder')}
              error={keyEmpty && keyError !== null}
              helperText={keyEmpty && keyError !== null ? keyError : undefined}
              slotProps={{
                ...params.slotProps,
                htmlInput: {
                  ...params.slotProps.htmlInput,
                  'aria-label': t('metadata.builder.condition.key'),
                  // Walidacja (kontrakt §4): warunek bez klucza oznaczony aria-invalid.
                  'aria-invalid': keyEmpty || undefined,
                },
              }}
            />
          )}
        />

        <TextField
          select
          size="small"
          disabled={disabled}
          value={condition.op}
          title={condition.op}
          onChange={(event) => onOpChange(event.target.value as MetaOp)}
          slotProps={{ htmlInput: { 'aria-label': t('metadata.builder.condition.op') } }}
          sx={{
            width: 150,
            flexShrink: 0,
            gridArea: 'op',
            // U2: długi operator („not contains”) obcięty wielokropkiem, pełny tekst w title.
            '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis' },
          }}
        >
          {META_OPS.map((op) => (
            <MenuItem key={op} value={op}>
              {op}
            </MenuItem>
          ))}
        </TextField>

        {isNoValueOp ? (
          // QA E6-1b-2 (A): przy `empty`/`not empty` brak edytora wartości, więc user nie widzi,
          // że warunek może wyglądać na zepsuty, gdy dokumenty nie mają pola — podpowiedź ⓘ
          // (decyzja Architekta) wyjaśnia sens operatora.
          <Tooltip title={t('metadata.builder.condition.noValueHint')}>
            {/* titleAccess: ikona w drzewie a11y (role img + nazwa), bez niej SvgIcon jest
              aria-hidden i podpowiedź nieosiągalna dla czytników ekranu. */}
            <InfoOutlinedIcon
              fontSize="small"
              titleAccess={t('metadata.builder.condition.noValueHint')}
              sx={{ color: 'action.active', flexShrink: 0, mt: '8px', gridArea: 'value' }}
            />
          </Tooltip>
        ) : isListOp ? (
          <Box sx={{ flex: '1 1 240px', minWidth: 0, gridArea: 'value' }}>
            <ChipListInput
              value={
                Array.isArray(condition.value)
                  ? condition.value
                  : stringValue === ''
                    ? []
                    : [stringValue]
              }
              onChange={onValueChange}
              inputLabel={t('metadata.builder.condition.value')}
              placeholder={t('metadata.builder.condition.valuePlaceholder')}
              error={showValueError ? valueError : null}
              removeLabel={(chip) => t('metadata.builder.value.remove', { value: chip })}
              disabled={disabled}
            />
          </Box>
        ) : hasFewKnownValues ? (
          // Combobox z podpowiedziami znanych wartości, ale z wolnym wpisem (MINOR T1b: wartość
          // nieobecna w dokumentach, np. `ustawa`, wpisywana jest klik + Enter — ścisły Select
          // przyjmowałby tylko pozycje z listy).
          <Autocomplete
            freeSolo
            openOnFocus
            disabled={disabled}
            options={knownValues}
            value={stringValue}
            // Defekt QA E6-1b-4 (T10): wpisany tekst bez Enter też jest wartością warunku —
            // klik „Zastosuj"/„Zapisz" (blur) nie może użyć starej wartości. 'reset' pomijamy:
            // to synchronizacja inputa ze zmienionym props `value` (np. konwersja operatora).
            onInputChange={(_event, next, reason) => {
              if (reason !== 'reset') onValueChange(next)
            }}
            onChange={(_event, next) => onValueChange(typeof next === 'string' ? next : '')}
            sx={{ flex: '1 1 240px', minWidth: 0, gridArea: 'value' }}
            renderInput={(params) => (
              <TextField
                {...params}
                size="small"
                title={stringValue}
                placeholder={t('metadata.builder.condition.valuePlaceholder')}
                error={showValueError}
                helperText={showValueError ? valueError : undefined}
                slotProps={{
                  ...params.slotProps,
                  htmlInput: {
                    ...params.slotProps.htmlInput,
                    'aria-label': t('metadata.builder.condition.value'),
                    'aria-invalid': showValueError || undefined,
                  },
                }}
              />
            )}
          />
        ) : (
          <TextField
            size="small"
            disabled={disabled}
            value={stringValue}
            title={stringValue}
            placeholder={t('metadata.builder.condition.valuePlaceholder')}
            error={showValueError}
            helperText={showValueError ? valueError : undefined}
            onChange={(event) => onValueChange(event.target.value)}
            slotProps={{
              htmlInput: {
                'aria-label': t('metadata.builder.condition.value'),
                'aria-invalid': showValueError || undefined,
              },
            }}
            sx={{ flex: '1 1 240px', minWidth: 0, gridArea: 'value' }}
          />
        )}

        <IconButton
          size="small"
          aria-label={t('metadata.builder.condition.remove')}
          disabled={disabled}
          onClick={onRemove}
          sx={{ alignSelf: 'flex-start', mt: '3px', gridArea: 'trash' }}
        >
          <DeleteOutlineRoundedIcon />
        </IconButton>
      </Stack>
    </Box>
  )
}
