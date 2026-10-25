/**
 * Historia przebiegów (brief T4 p. 5): lista malejąco po `id` z chipem statusu, czasami
 * i licznikami oraz doczytywaniem kursorem `next_after_id`. Pierwszą stronę bierze
 * `integrationRunsQueryOptions`, a kolejne pobieramy lokalnie przez `fetchQuery`
 * (kontrakt §1 — `queries.ts` zostaje bez zmian). Klik przebiegu otwiera jego zdarzenia.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '../../../api/client'
import type { components } from '../../../api/schema.gen'

import { wdCall, wdErrorKey } from '../wdClient'

import { RunEvents } from './RunEvents'
import { StatusChip } from './StatusChip'
import { integrationKeys, integrationRunsQueryOptions } from './queries'
import type { IntegrationRun } from './queries'

type RunsPage = components['schemas']['CursorPage_IntegrationRun_']

/** Rozmiar strony historii — zgodny z pierwszym pobraniem z `queries.ts` (kontrakt §1). */
const RUNS_PAGE_SIZE = 20

function formatTime(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

function RunRow(props: {
  run: IntegrationRun
  language: string
  onOpen: (runId: number) => void
}): JSX.Element {
  const { run, language, onOpen } = props
  const { t } = useTranslation()
  // Liczniki w jednej linii: dodane, zmienione, usunięte, błędy.
  const counts = [
    `${t('integrations.details.counts.added')} ${run.added}`,
    `${t('integrations.details.counts.updated')} ${run.updated}`,
    `${t('integrations.details.counts.deleted')} ${run.deleted}`,
    `${t('integrations.details.counts.failed')} ${run.failed}`,
  ].join(' · ')

  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
      <Button size="small" data-testid={`integration-run-${run.id}`} onClick={() => onOpen(run.id)}>
        {run.id}
      </Button>
      <StatusChip status={run.status} />
      <Typography variant="body2" color="text.secondary">
        {`${formatTime(run.started_at, language)} → ${formatTime(run.finished_at, language)}`}
      </Typography>
      <Typography variant="body2" sx={{ flexGrow: 1 }}>
        {counts}
      </Typography>
    </Stack>
  )
}

export type RunsListProps = { integrationId: number }

export function RunsList(props: RunsListProps): JSX.Element {
  const { integrationId } = props
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const first = useQuery(integrationRunsQueryOptions(integrationId))
  const [moreItems, setMoreItems] = useState<IntegrationRun[]>([])
  const [cursor, setCursor] = useState<number | null | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [moreError, setMoreError] = useState<unknown>(null)
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)

  const nextCursor = cursor === undefined ? (first.data?.next_after_id ?? null) : cursor
  const rows = [...(first.data?.items ?? []), ...moreItems]

  /** Dociąga kolejną stronę kursorem; błąd pokazujemy, a `loading` gasimy w `finally`. */
  async function loadMore(): Promise<void> {
    if (nextCursor === null) return
    setLoading(true)
    try {
      const page = await queryClient.fetchQuery({
        queryKey: [...integrationKeys.runs(integrationId), nextCursor],
        queryFn: () =>
          wdCall<RunsPage>(
            api.GET('/api/wd/v1/integrations/{integration_id}/runs', {
              params: {
                path: { integration_id: integrationId },
                query: { limit: RUNS_PAGE_SIZE, after_id: nextCursor },
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

  let content: JSX.Element
  if (first.isError) {
    content = <Alert severity="error">{t(wdErrorKey(first.error))}</Alert>
  } else if (rows.length === 0 && first.isPending) {
    content = <CircularProgress size={20} />
  } else if (rows.length === 0) {
    content = <Typography color="text.secondary">{t('integrations.runs.empty')}</Typography>
  } else {
    content = (
      <Stack spacing={1}>
        {rows.map((run) => (
          <RunRow key={run.id} run={run} language={i18n.language} onOpen={setSelectedRunId} />
        ))}
        {moreError === null ? null : <Alert severity="error">{t(wdErrorKey(moreError))}</Alert>}
        {nextCursor === null ? null : (
          <Button
            size="small"
            data-testid="integration-runs-more"
            disabled={loading}
            onClick={() => void loadMore()}
          >
            {t('integrations.runs.more')}
          </Button>
        )}
      </Stack>
    )
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2">{t('integrations.runs.title')}</Typography>
      {content}
      {selectedRunId === null ? (
        <Typography variant="body2" color="text.secondary">
          {t('integrations.events.noRun')}
        </Typography>
      ) : (
        <RunEvents runId={selectedRunId} />
      )}
    </Stack>
  )
}
