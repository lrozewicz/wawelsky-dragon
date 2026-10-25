/**
 * Ekran wyszukiwania `/search/:id` (08 §7.8, kontrakt WP E4-4b §4): ekran startowy z powitaniem
 * i dużym paskiem, a po wysłaniu pytania — przyklejony pasek, karta podsumowania ze strumienia,
 * trafienia z filtrem plików i paginacją oraz chipy pytań pokrewnych. Zębatka otwiera ustawienia
 * wyszukiwarki; otwierają się one same, gdy nie wybrano jeszcze żadnej bazy wiedzy.
 *
 * Nowe pytanie (pasek albo chip) startuje od pierwszej strony bez filtra i uruchamia równolegle
 * podsumowanie (`useSearchSummary`) i trafienia (`useSearchHits`); liczniki filtra pochodzą
 * z ostatniego zapytania BEZ filtra, dlatego trzymamy je w stanie strony, a nie z odpowiedzi
 * zawężonej wybranymi plikami.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import IconButton from '@mui/material/IconButton'
import MenuItem from '@mui/material/MenuItem'
import Pagination from '@mui/material/Pagination'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import type { UsePaginationItem } from '@mui/material/usePagination'
import { useRouteContext } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import PageContainer from '../../components/PageContainer'
import { QueryError } from '../../components/QueryError'
import { DocumentPreviewDrawer } from '../chats/preview/DocumentPreviewDrawer'
import type { DocAgg } from '../datasets/retrieval/queries'

import { FileFilter } from './components/FileFilter'
import { HitsList } from './components/HitsList'
import { RelatedChips } from './components/RelatedChips'
import { SearchBar } from './components/SearchBar'
import { SummaryCard } from './components/SummaryCard'
import { useRelatedQuestions } from './hooks/useRelatedQuestions'
import { useSearchHits } from './hooks/useSearchHits'
import { useSearchSummary } from './hooks/useSearchSummary'
import { searchQueryOptions } from './queries'
import type { RawSearchConfig } from './queries'
import { SearchSettingsDrawer } from './settings/SearchSettingsDrawer'

export type SearchPageProps = { searchId: string }

/** Stabilna konfiguracja, zanim wyszukiwarka się wczyta (klucz zapytań nie może drgać). */
const EMPTY_CONFIG: RawSearchConfig = {}

/** Rozmiary strony dostępne w wyborze (kontrakt §3). */
const PAGE_SIZES = [10, 20, 50]

/** Domyślny rozmiar strony. */
const DEFAULT_PAGE_SIZE = 10

/** Czy wyszukiwarka nie ma jeszcze żadnej bazy wiedzy (kontrakt §4 — auto-otwarcie ustawień). */
function hasNoKb(config: RawSearchConfig): boolean {
  const kbIds = config.kb_ids
  return !Array.isArray(kbIds) || kbIds.length === 0
}

export function SearchPage(props: SearchPageProps): JSX.Element {
  const { searchId } = props
  const { t } = useTranslation()
  // Kontekst trasy jest częściowy (`strict: false`) — bierzemy z niego tylko profil (jak `HomePage`).
  const user = useRouteContext({ strict: false, select: (context) => context.auth?.user ?? null })
  const nickname = user !== null && user.nickname !== '' ? user.nickname : (user?.email ?? '')

  const app = useQuery(searchQueryOptions(searchId))
  const config = app.data?.search_config ?? EMPTY_CONFIG

  // Bieżące zapytanie: `null` = ekran startowy. Zmiana pytania wraca na pierwszą stronę bez filtra.
  const [question, setQuestion] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [docIds, setDocIds] = useState<string[]>([])
  // Liczniki filtra z ostatniej odpowiedzi BEZ filtra (kontrakt §4) wraz z jej źródłem.
  const [aggsState, setAggsState] = useState<{ source: unknown; aggs: DocAgg[] }>({
    source: null,
    aggs: [],
  })
  const [preview, setPreview] = useState<{ docId: string; docName: string } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [autoOpened, setAutoOpened] = useState(false)

  // Korekta stanu przy wejściu danych: brak baz wiedzy otwiera szufladę ustawień samoczynnie.
  if (!autoOpened && app.data !== undefined && hasNoKb(app.data.search_config)) {
    setAutoOpened(true)
    setSettingsOpen(true)
  }

  const summaryEnabled = config.summary === true
  const relatedEnabled = config.related_search === true

  const summary = useSearchSummary(searchId)
  const hits = useSearchHits(
    question === null ? null : { question, config, page, pageSize, docIds },
  )
  const related = useRelatedQuestions(searchId, question, relatedEnabled)

  // Liczniki bierzemy tylko z odpowiedzi bez filtra — zawężona odpowiedź ma `doc_aggs` policzone
  // po wybranych plikach. `isPlaceholderData` odsiewa jeszcze poprzednią odpowiedź (przy zmianie
  // filtra/strony), żeby liczniki nie mrugały. Korekta stanu przy wejściu danych (jak w `SearchBar`).
  if (
    docIds.length === 0 &&
    !hits.isPlaceholderData &&
    hits.data !== undefined &&
    aggsState.source !== hits.data
  ) {
    setAggsState({ source: hits.data, aggs: hits.data.doc_aggs })
  }
  const aggs = aggsState.aggs

  /** Nowe pytanie (pasek albo chip): pierwsza strona, bez filtra; podsumowanie startuje równolegle. */
  function runQuery(text: string): void {
    // Wyścig z wczytaniem `search_config` (defekt QA-UI E4-4b): ekran startowy pokazuje pasek
    // jeszcze przed odpowiedzią `GET /searches/:id`, a bez konfiguracji retrieval poszedłby
    // z pustym `EMPTY_CONFIG` (bez `kb_ids` i progów) — do tego czasu pytanie ignorujemy.
    if (app.data === undefined) return
    setQuestion(text)
    setPage(1)
    setDocIds([])
    if (summaryEnabled) void summary.start(text)
  }

  function openDocument(docId: string, docName: string): void {
    setPreview({ docId, docName })
  }

  function changeFilter(ids: string[]): void {
    setDocIds(ids)
    setPage(1)
  }

  function changePageSize(size: number): void {
    setPageSize(size)
    setPage(1)
  }

  const total = hits.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // Etykiety dostępności paginacji (kontrakt WP E4-H1 §„Klucze i18n”): domyślne MUI są angielskie,
  // a obszar searches jest tłumaczony — stąd własna funkcja zamiast motywu globalnego.
  function paginationLabel(
    type: UsePaginationItem['type'],
    page: UsePaginationItem['page'],
    selected: boolean,
  ): string {
    switch (type) {
      case 'page':
        return selected
          ? t('searches.hits.page.current', { page })
          : t('searches.hits.page.goTo', { page })
      case 'first':
        return t('searches.hits.page.first')
      case 'last':
        return t('searches.hits.page.last')
      case 'next':
        return t('searches.hits.page.next')
      case 'previous':
        return t('searches.hits.page.previous')
      default:
        // Wielokropki (`start-ellipsis`/`end-ellipsis`) nie są interaktywne — bez etykiety.
        return ''
    }
  }

  const gear = (
    <IconButton aria-label={t('searches.settings.open')} onClick={() => setSettingsOpen(true)}>
      <SettingsOutlinedIcon />
    </IconButton>
  )

  /** Ekran startowy: powitanie z nickiem i duży pasek (kontrakt §4). */
  const start = (
    <Stack spacing={4} sx={{ alignItems: 'center', mt: 8 }}>
      <Typography variant="h4" data-testid="search-welcome">
        {t('searches.start.welcome', { nickname })}
      </Typography>
      <SearchBar value="" onSubmit={runQuery} large />
    </Stack>
  )

  /** Wyniki: przyklejony pasek, podsumowanie, chipy pokrewne, trafienia, filtr i paginacja. */
  const results = (
    <Stack spacing={2}>
      <SearchBar value={question ?? ''} onSubmit={runQuery} sticky />
      {summaryEnabled ? (
        <SummaryCard phase={summary.phase} state={summary.state} onOpenDocument={openDocument} />
      ) : null}
      <RelatedChips items={related.data ?? []} onPick={runQuery} />
      {hits.isError ? (
        // Kontrakt WP E3-7 §C6: błąd trafień to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
        <QueryError message={t('searches.hits.error')} onRetry={() => void hits.refetch()} />
      ) : (
        <HitsList
          chunks={hits.data?.chunks ?? []}
          question={question ?? ''}
          onOpenDocument={openDocument}
        />
      )}
      <FileFilter aggs={aggs} selected={docIds} onChange={changeFilter} />
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: 'center', justifyContent: 'space-between' }}
      >
        <Typography data-testid="search-total">
          {t('searches.hits.total', { count: total })}
        </Typography>
        <TextField
          select
          size="small"
          label={t('searches.hits.pageSize')}
          value={pageSize}
          onChange={(event) => changePageSize(Number(event.target.value))}
        >
          {PAGE_SIZES.map((size) => (
            <MenuItem key={size} value={size}>
              {size}
            </MenuItem>
          ))}
        </TextField>
        <Pagination
          aria-label={t('searches.hits.pagination')}
          count={totalPages}
          page={page}
          getItemAriaLabel={paginationLabel}
          onChange={(_event, next) => setPage(next)}
        />
      </Stack>
    </Stack>
  )

  return (
    <PageContainer title={app.data?.name} actions={gear}>
      {question === null ? start : results}
      {app.data !== undefined ? (
        <SearchSettingsDrawer
          app={app.data}
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}
      <DocumentPreviewDrawer
        documentId={preview?.docId ?? null}
        documentName={preview?.docName}
        onClose={() => setPreview(null)}
      />
    </PageContainer>
  )
}
