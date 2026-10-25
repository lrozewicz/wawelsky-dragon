/**
 * Pasek narzędzi zakładki Pliki (kontrakt WP E3-3b §T5): szukaj (debounce 400 ms), filtry
 * „Typ pliku” (`suffix`) i „Status” (`run`, kody 0–5) oraz przycisk „Prześlij plik”.
 * Slot `metadataFilter` (WP E6-1b T5b) dokłada przycisk „Filtr metadanych” i chip aktywnego
 * filtra; `showAdd=false` (pusty wynik filtra metadanych) chowa „Prześlij plik”, bo to nie jest
 * stan pustego datasetu. Każda zmiana filtra wraca na stronę 1 — inaczej użytkownik zostałby na
 * nieistniejącej stronie. Wyszukiwanie trzyma lokalny tekst, a `query` i `onChange` czytamy
 * z refa, żeby opóźnienie odmierzane było od ostatniego znaku, a nie od ostatniego renderu
 * rodzica.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import type { DocumentsQuery } from './queries'

/** Opóźnienie wyszukiwania (kontrakt §T5). */
export const SEARCH_DEBOUNCE_MS = 400

/** Rozszerzenia z kontraktu §T5 — wartość trafia do filtra `suffix`. */
const FILE_TYPES = ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md', 'csv', 'html', 'json'] as const

/** Kody `run` z kontraktu §Fakty API i ich etykiety `datasets.files.status.*`. */
const STATUS_OPTIONS = [
  { code: '0', state: 'idle' },
  { code: '1', state: 'running' },
  { code: '2', state: 'cancelled' },
  { code: '3', state: 'done' },
  { code: '4', state: 'failed' },
  { code: '5', state: 'queued' },
] as const

export type FilesToolbarProps = {
  query: DocumentsQuery
  /** Pełny nowy stan listy — filtr ustawia `page: 1`. */
  onChange: (query: DocumentsQuery) => void
  /** Otwiera dialog przesyłania plików. */
  onAdd: () => void
  /** Slot filtra metadanych (WP E6-1b T5b): przycisk „Filtr metadanych” i chip aktywnego filtra. */
  metadataFilter?: ReactNode
  /** `false` przy pustym wyniku filtra metadanych — to nie stan pustego datasetu z uploadem
   * (kontrakt WP E6-1b §4); domyślnie przycisk jest widoczny. */
  showAdd?: boolean
}

export function FilesToolbar(props: FilesToolbarProps): JSX.Element {
  const { query, onChange, onAdd, metadataFilter, showAdd = true } = props
  const { t } = useTranslation()
  const [search, setSearch] = useState(query.keywords)
  const latest = useRef({ query, onChange })

  useEffect(() => {
    latest.current = { query, onChange }
  })

  useEffect(() => {
    if (search === latest.current.query.keywords) return
    const timer = setTimeout(() => {
      const current = latest.current
      current.onChange({ ...current.query, keywords: search, page: 1 })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [search])

  return (
    // `useFlexGap` (CSS `gap`): przy zawijaniu elementy nowego wiersza startują przy lewej
    // krawędzi — `margin-left` ze `spacing` wciskało je o 16 px względem wyszukiwania (SC-E5-H8z-03).
    // `minWidth: 0`: pasek nie wykręca przewijacza w rodzicach z zawijaniem, a chip filtra
    // metadanych kurczy się zamiast przepychać „Prześlij plik" do nowego wiersza (QA V12-z-1 C15).
    <Stack
      direction="row"
      spacing={2}
      useFlexGap
      sx={{ alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}
    >
      <TextField
        size="small"
        label={t('datasets.files.search')}
        value={search}
        data-testid="files-search"
        onChange={(event) => setSearch(event.target.value)}
        sx={{ minWidth: 240 }}
      />

      <TextField
        select
        size="small"
        label={t('datasets.files.filter.type')}
        value={query.suffix[0] ?? ''}
        data-testid="files-filter-type"
        onChange={(event) =>
          onChange({
            ...query,
            suffix: event.target.value === '' ? [] : [event.target.value],
            page: 1,
          })
        }
        sx={{ minWidth: 160 }}
      >
        <MenuItem value="">{t('datasets.files.filter.all')}</MenuItem>
        {FILE_TYPES.map((suffix) => (
          <MenuItem key={suffix} value={suffix}>
            {suffix}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        size="small"
        label={t('datasets.files.filter.status')}
        value={query.run[0] ?? ''}
        data-testid="files-filter-status"
        onChange={(event) =>
          onChange({
            ...query,
            run: event.target.value === '' ? [] : [event.target.value],
            page: 1,
          })
        }
        sx={{ minWidth: 160 }}
      >
        <MenuItem value="">{t('datasets.files.filter.all')}</MenuItem>
        {STATUS_OPTIONS.map((option) => (
          <MenuItem key={option.code} value={option.code}>
            {t(`datasets.files.status.${option.state}`)}
          </MenuItem>
        ))}
      </TextField>

      {/* Filtr metadanych (T5b) na własnym wierszu wąskiego ekranu: slot wypełnia cały wiersz,
          więc „Prześlij plik” startuje od lewej krawędzi jak pole wyszukiwania (regresja SC-E5-H8z-03
          d po T5b: przycisk doklejony do wiersza filtra, x=165.6 vs 16). Od `md` slot znika
          z pudełka (`display: contents`) — przycisk i chip wracają jako zwykłe elementy jednego
          wiersza, jak przed poprawką na desktopie. */}
      {metadataFilter !== undefined ? (
        <Box
          sx={{
            display: { xs: 'flex', md: 'contents' },
            flexBasis: { xs: '100%', md: 'auto' },
            alignItems: 'center',
            gap: 2,
          }}
        >
          {metadataFilter}
        </Box>
      ) : null}

      {showAdd ? (
        <Button variant="contained" data-testid="files-add" onClick={onAdd}>
          {t('datasets.files.add')}
        </Button>
      ) : null}
    </Stack>
  )
}
