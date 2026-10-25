/**
 * Pasek wyszukiwania (kontrakt WP E4-4b §4): pole pytania z przyciskiem wysyłki.
 *
 * Enter w polu albo przycisk wołają `onSubmit` z tekstem po `trim`; sam biały znak nic nie robi.
 * Pole trzyma własny szkic (użytkownik pisze bez udziału wołającego), ale synchronizuje się
 * z `value` — zmiana propsa (np. wybór chipa „Pytania pokrewne”) podstawia nowy tekst. Stosujemy
 * wzorzec Reacta „korekta stanu przy zmianie propsa”: porównanie z poprzednią wartością w stanie,
 * żeby nie nadpisywać szkicu przy każdym renderze.
 */

import { useState } from 'react'
import type { JSX, KeyboardEvent } from 'react'
import SearchIcon from '@mui/icons-material/Search'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

export type SearchBarProps = {
  value: string
  onSubmit: (q: string) => void
  /** Duże pole wyśrodkowane — ekran startowy. */
  large?: boolean
  /** Pasek przyklejony do góry viewportu — ekran wyników. */
  sticky?: boolean
}

/** Szerokość dużego pola na ekranie startowym. */
const LARGE_MAX_WIDTH = 720

export function SearchBar(props: SearchBarProps): JSX.Element {
  const { value, onSubmit, large = false, sticky = false } = props
  const { t } = useTranslation()

  const [text, setText] = useState(value)
  const [lastValue, setLastValue] = useState(value)
  if (lastValue !== value) {
    setLastValue(value)
    setText(value)
  }

  function submit(): void {
    const trimmed = text.trim()
    if (trimmed === '') return
    onSubmit(trimmed)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== 'Enter') return
    submit()
  }

  return (
    <Box
      data-testid="search-bar"
      sx={{
        ...(sticky ? { position: 'sticky', top: 0, zIndex: 1, bgcolor: 'background.paper' } : {}),
        ...(large ? { width: '100%', maxWidth: LARGE_MAX_WIDTH, mx: 'auto' } : {}),
      }}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <TextField
          fullWidth
          size={large ? 'medium' : 'small'}
          placeholder={t('searches.start.placeholder')}
          value={text}
          onChange={(event) => setText(event.target.value)}
          slotProps={{
            htmlInput: { 'aria-label': t('searches.bar.label'), onKeyDown: handleKeyDown },
            ...(large ? { input: { sx: { fontSize: '1.25rem', py: 1.5 } } } : {}),
          }}
        />
        <IconButton
          aria-label={t('searches.bar.submit')}
          size={large ? 'large' : 'medium'}
          onClick={submit}
        >
          <SearchIcon />
        </IconButton>
      </Stack>
    </Box>
  )
}
