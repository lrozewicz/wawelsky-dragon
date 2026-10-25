/**
 * Wspólny edytor listy chipów (kontrakt WP E6-1b §4): Enter dodaje, Backspace na pustym polu
 * nic nie usuwa (usuwanie tylko przez × z `aria-label`), duplikaty i puste pomijane. Z opcjami
 * działa jak combobox z wpisem własnym. Używają go: warunki `in`/`not in` i klucze trybu
 * półautomatycznego (kreator, T3) oraz „Dozwolona wartość” formularza pól datasetu (T4).
 */
import { useState } from 'react'
import Autocomplete from '@mui/material/Autocomplete'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import TextField from '@mui/material/TextField'
import CloseIcon from '@mui/icons-material/Close'

export type ChipListInputProps = {
  /** Bieżące wartości (kolejność istotna). */
  value: string[]
  /** Podmiana całej listy (Enter dodaje na końcu, × usuwa wskazany chip). */
  onChange: (next: string[]) => void
  /** aria-label pola tekstowego (kontrakt §4: „Wartość”, „Dozwolona wartość”, „Dodaj klucz”). */
  inputLabel: string
  /** aria-label przycisku × chipu, z wartością chipu („Usuń wartość <v>”, „Usuń klucz <k>”). */
  removeLabel: (chip: string) => string
  /** Podpowiedzi pola (combobox); bez podanej listy pole przyjmuje dowolny tekst. */
  options?: string[]
  disabled?: boolean
  /** Widoczna etykieta pola (opcjonalna; `inputLabel` zostaje nazwą dostępną). */
  label?: string
  /** Placeholder pustego pola (widoczny tylko bez chipów). */
  placeholder?: string
  /** Komunikat błędu pola (już przetłumaczony) — ramka błędu i helperText; `null`/brak = bez błędu. */
  error?: string | null
}

/** Nowa lista chipów: trim, pominięcie pustych i duplikatów, kolejność zachowana. */
function normalize(items: Array<string | { inputValue: string }>): string[] {
  const seen = new Set<string>()
  const chips: string[] = []
  for (const item of items) {
    const chip = typeof item === 'string' ? item.trim() : item.inputValue.trim()
    if (chip === '' || seen.has(chip)) continue
    seen.add(chip)
    chips.push(chip)
  }
  return chips
}

export function ChipListInput(props: ChipListInputProps) {
  const {
    value,
    onChange,
    inputLabel,
    removeLabel,
    options,
    disabled = false,
    placeholder,
    label,
    error = null,
  } = props
  const suggestions = options ?? []
  // QA E6-1b-1 (D1, MAJOR): popup kontrolowany własnym stanem i ZAWSZE zdefiniowany —
  // `useControlled` MUI rozstrzyga controlled/uncontrolled na PIERWSZYM renderze, więc
  // warunkowy `open={hasSuggestions ? undefined : false}` przy opcjach przychodzących asynchronicznie
  // (podsumowanie metadanych) trwale martwi popup. Otwarcie pilnuje MUI (onOpen/onClose),
  // widoczność — brak opcji (QA: pusty panel podpowiedzi przy fokusie w polu bez podpowiedzi).
  const [popupRequested, setPopupRequested] = useState(false)
  const hasSuggestions = suggestions.length > 0

  return (
    <Autocomplete
      multiple
      freeSolo
      disabled={disabled}
      // QA E6-1b-1 (D1, MAJOR): po dodaniu chipów Autocomplete rysuje pływający „×” (clear
      // indicator) wewnątrz kontenera chipów — chipy mają własne × z `removeLabel`, więc to
      // zbędny duplikat; `disableClearable` usuwa go z DOM (MUI: hasClearIcon = !disableClearable
      // && dirty).
      disableClearable
      // Bez podanych opcji popup niczego nie podpowie — trwale zamknięty i bez strzałki
      // (QA E6-1b-1 D1: pusty panel podpowiedzi przy fokusie). Z opcjami combobox działa jak dotąd.
      open={popupRequested && hasSuggestions}
      onOpen={() => setPopupRequested(true)}
      onClose={() => setPopupRequested(false)}
      popupIcon={hasSuggestions ? undefined : null}
      // Motyw (D-maj1) daje OutlinedInput stałą wysokość 2,5 rem; zawijane chipy wymagają
      // rosnącego pola, inaczej nadlewają się na kolejne sekcje (U5; SC-01 „długie dane”).
      sx={{ '& .MuiOutlinedInput-root': { height: 'auto', minHeight: '2.5rem' } }}
      options={suggestions}
      value={value}
      openOnFocus={suggestions.length > 0}
      selectOnFocus
      clearOnBlur
      handleHomeEndKeys
      onChange={(_event, next) => onChange(normalize(next))}
      onKeyDown={(event) => {
        // Backspace na pustym polu NIE usuwa chipa (kontrakt §4) — usuwanie tylko przez ×.
        if (event.key === 'Backspace' && (event.target as HTMLInputElement).value === '') {
          event.defaultMuiPrevented = true
        }
      }}
      renderValue={(chips, getItemProps) =>
        chips.map((chip, index) => {
          const { key, ...itemProps } = getItemProps({ index })
          return (
            <Chip
              key={key}
              label={chip}
              size="small"
              // U2: długa wartość → wielokropek + pełna treść w podpowiedzi.
              title={chip}
              sx={{
                maxWidth: '100%',
                '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' },
              }}
              // × jako prawdziwy przycisk (defekt T3: aria-label na samym svg nie daje
              // role="button" — e2e klika `getByRole('button', { name: 'Usuń …' })`). Motyw
              // projektu stylizuje IconButton na 36×36 z ramką i tłem — w chipie 20 px
              // skalujemy do 20×20 bez ramki i tła (obserwowane w przeglądarce 2026-10-13).
              deleteIcon={
                <IconButton
                  size="small"
                  aria-label={removeLabel(chip)}
                  sx={{
                    p: 0.25,
                    width: 20,
                    height: 20,
                    borderRadius: '50%',
                    border: 0,
                    backgroundColor: 'transparent',
                    color: 'inherit',
                  }}
                >
                  <CloseIcon sx={{ fontSize: 16 }} />
                </IconButton>
              }
              {...itemProps}
            />
          )
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
          error={error !== null}
          helperText={error ?? undefined}
          slotProps={{
            // params.slotProps.htmlInput niosą okablowanie Autocomplete (value/onChange/role) — scalane.
            ...params.slotProps,
            htmlInput: {
              ...params.slotProps.htmlInput,
              'aria-label': inputLabel,
              'aria-invalid': error !== null || undefined,
            },
          }}
        />
      )}
    />
  )
}
