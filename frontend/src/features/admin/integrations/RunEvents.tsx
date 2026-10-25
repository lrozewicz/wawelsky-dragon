/**
 * Zdarzenia przebiegu (brief T4 p. 6): lista rosnąco po `id`, poziom jako chip, filtr poziomu
 * i doczytywanie kursorem `next_after_id`. Pierwszą stronę bierze `runEventsQueryOptions`,
 * a kolejne pobieramy lokalnie przez `fetchQuery` (kontrakt §1 — `queries.ts` zostaje bez zmian).
 * Filtr i przebieg kluczują listę, więc zmiana któregokolwiek zaczyna zbiór od zera.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import type { ChipProps } from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '../../../api/client'
import type { components } from '../../../api/schema.gen'

import { wdCall, wdErrorKey } from '../wdClient'

import { integrationKeys, runEventsQueryOptions } from './queries'
import type { IntegrationEvent } from './queries'

type EventsPage = components['schemas']['CursorPage_IntegrationEvent_']

/** Rozmiar strony zdarzeń — zgodny z pierwszym pobraniem z `queries.ts` (kontrakt §1). */
const EVENTS_PAGE_SIZE = 100

/** Poziomy filtra; schemat API zna `warn`, a kontrakt starsze `warning` — oba to ostrzeżenie. */
const LEVELS = ['info', 'warn', 'error'] as const
const LEVEL_COLORS: Record<string, ChipProps['color']> = {
  info: 'info',
  warn: 'warning',
  warning: 'warning',
  error: 'error',
}

/** Klucz i18n poziomu; `warning` to starsze `warn`, nieznane poziomy pokazujemy surowo (`null`). */
function levelKey(level: string): string | null {
  if (level === 'warning') return 'integrations.events.level.warn'
  if (level === 'info' || level === 'warn' || level === 'error') {
    return `integrations.events.level.${level}`
  }
  return null
}

function formatTime(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

function EventRow(props: { event: IntegrationEvent; language: string }): JSX.Element {
  const { event, language } = props
  const { t } = useTranslation()
  const details = [event.file_path, event.drive_name].filter((value) => value !== null).join(' · ')
  const key = levelKey(event.level)

  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <Chip
          size="small"
          color={LEVEL_COLORS[event.level] ?? 'default'}
          label={key === null ? event.level : t(key)}
        />
        <Typography variant="body2" color="text.secondary">
          {formatTime(event.created_at, language)}
        </Typography>
      </Stack>
      <Typography variant="body2">{event.message}</Typography>
      {details === '' ? null : (
        <Typography variant="caption" color="text.secondary">
          {details}
        </Typography>
      )}
    </Stack>
  )
}

/** Lista zdarzeń jednego poziomu; kluczowana po `runId`/`level`, więc kursor nie przecieka. */
function EventList(props: { runId: number; level: string }): JSX.Element {
  const { runId, level } = props
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const first = useQuery(runEventsQueryOptions(runId, level))
  const [moreItems, setMoreItems] = useState<IntegrationEvent[]>([])
  const [cursor, setCursor] = useState<number | null | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [moreError, setMoreError] = useState<unknown>(null)

  const nextCursor = cursor === undefined ? (first.data?.next_after_id ?? null) : cursor
  const rows = [...(first.data?.items ?? []), ...moreItems]

  /** Dociąga kolejną stronę kursorem; błąd pokazujemy, a `loading` gasimy w `finally`. */
  async function loadMore(): Promise<void> {
    if (nextCursor === null) return
    setLoading(true)
    try {
      const page = await queryClient.fetchQuery({
        queryKey: [...integrationKeys.events(runId, level), nextCursor],
        queryFn: () =>
          wdCall<EventsPage>(
            api.GET('/api/wd/v1/runs/{run_id}/events', {
              params: {
                path: { run_id: runId },
                query: {
                  level: level === '' ? undefined : (level as 'info' | 'warn' | 'error'),
                  limit: EVENTS_PAGE_SIZE,
                  after_id: nextCursor,
                },
              },
            }),
          ),
      })
      setMoreItems((current) => [...current, ...page.items])
      setCursor(page.next_after_id)
    } catch (error) {
      setMoreError(error)
    } finally {
      setLoading(false)
    }
  }

  if (first.isError) {
    return <Alert severity="error">{t(wdErrorKey(first.error))}</Alert>
  }
  if (rows.length === 0 && first.isPending) {
    return <CircularProgress size={20} />
  }
  if (rows.length === 0) {
    return <Typography color="text.secondary">{t('integrations.events.empty')}</Typography>
  }

  return (
    <Stack spacing={1.5}>
      {rows.map((event) => (
        <EventRow key={event.id} event={event} language={i18n.language} />
      ))}
      {moreError === null ? null : <Alert severity="error">{t(wdErrorKey(moreError))}</Alert>}
      {nextCursor === null ? null : (
        <Button
          size="small"
          data-testid="integration-events-more"
          disabled={loading}
          onClick={() => void loadMore()}
        >
          {t('integrations.events.more')}
        </Button>
      )}
    </Stack>
  )
}

export type RunEventsProps = { runId: number }

export function RunEvents(props: RunEventsProps): JSX.Element {
  const { runId } = props
  const { t } = useTranslation()
  const [level, setLevel] = useState('')

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
          {t('integrations.events.title')}
        </Typography>
        <TextField
          select
          size="small"
          label={t('integrations.events.level.label')}
          value={level}
          sx={{ minWidth: 180 }}
          onChange={(event) => setLevel(event.target.value)}
        >
          <MenuItem value="">{t('integrations.events.level.all')}</MenuItem>
          {LEVELS.map((known) => (
            <MenuItem key={known} value={known}>
              {t(`integrations.events.level.${known}`)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <EventList key={`${runId}-${level}`} runId={runId} level={level} />
    </Stack>
  )
}
