/**
 * Pasek narzędzi listy chunków (kontrakt WP E3-H2a §K3): przełącznik widoku Pełny/Skrócony,
 * filtr dostępności (serwerowy — panel wysyła `available`), szukanie z debounce 400 ms i przycisk
 * „Nowy chunk”. Widok i filtr działają natychmiast, a wyszukiwanie trzyma lokalny tekst i strzela
 * dopiero po pauzie w pisaniu.
 * Wzór odroczenia: `features/datasets/files/FilesToolbar.tsx` — `keywords` i callback czytamy
 * z refa, żeby termin liczył się od ostatniego znaku, a nie od ostatniego renderu rodzica.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import AddIcon from '@mui/icons-material/Add'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import { useTranslation } from 'react-i18next'

import type { ChunksFilter } from './queries'

export type { ChunksFilter }

export type ChunksToolbarProps = {
  expanded: boolean
  onExpandedChange: (v: boolean) => void
  filter: ChunksFilter
  onFilterChange: (f: ChunksFilter) => void
  keywords: string
  onKeywordsChange: (v: string) => void
  onAdd: () => void
}

/** Opóźnienie wyszukiwania (kontrakt §ChunksToolbar). */
export const CHUNKS_SEARCH_DEBOUNCE_MS = 400

/** Wartości przełącznika widoku — tłumaczone na `expanded`. */
const VIEW_FULL = 'full'
const VIEW_SHORT = 'short'

export function ChunksToolbar(props: ChunksToolbarProps): JSX.Element {
  const { expanded, onExpandedChange, filter, onFilterChange, keywords, onKeywordsChange, onAdd } =
    props
  const { t } = useTranslation()
  const [search, setSearch] = useState(keywords)
  const latest = useRef({ keywords, onKeywordsChange })

  useEffect(() => {
    latest.current = { keywords, onKeywordsChange }
  })

  useEffect(() => {
    if (search === latest.current.keywords) return
    const timer = setTimeout(() => {
      latest.current.onKeywordsChange(search)
    }, CHUNKS_SEARCH_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [search])

  return (
    <Stack
      direction="row"
      spacing={2}
      data-testid="chunks-toolbar"
      sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 2 }}
    >
      <ToggleButtonGroup
        exclusive
        size="small"
        data-testid="chunks-view-toggle"
        value={expanded ? VIEW_FULL : VIEW_SHORT}
        onChange={(_event, next: string | null) => {
          if (next !== null) onExpandedChange(next === VIEW_FULL)
        }}
      >
        <ToggleButton value={VIEW_FULL}>{t('chunks.view.full')}</ToggleButton>
        <ToggleButton value={VIEW_SHORT}>{t('chunks.view.short')}</ToggleButton>
      </ToggleButtonGroup>

      <ToggleButtonGroup
        exclusive
        size="small"
        data-testid="chunks-filter"
        aria-label={t('chunks.filter.label')}
        value={filter}
        onChange={(_event, next: ChunksFilter | null) => {
          if (next !== null) onFilterChange(next)
        }}
      >
        <ToggleButton value="all" data-testid="chunks-filter-all">
          {t('chunks.filter.all')}
        </ToggleButton>
        <ToggleButton value="enabled" data-testid="chunks-filter-enabled">
          {t('chunks.filter.enabled')}
        </ToggleButton>
        <ToggleButton value="disabled" data-testid="chunks-filter-disabled">
          {t('chunks.filter.disabled')}
        </ToggleButton>
      </ToggleButtonGroup>

      <TextField
        size="small"
        value={search}
        placeholder={t('chunks.search.placeholder')}
        slotProps={{
          htmlInput: {
            'data-testid': 'chunks-search',
            'aria-label': t('chunks.search.placeholder'),
          },
        }}
        onChange={(event) => {
          setSearch(event.target.value)
        }}
        sx={{ minWidth: 240 }}
      />

      <Button variant="contained" data-testid="chunks-add" startIcon={<AddIcon />} onClick={onAdd}>
        {t('chunks.add')}
      </Button>
    </Stack>
  )
}
