/**
 * Zakładka „Test retrievalu” szczegółów datasetu (kontrakt WP E3-4b §R/RetrievalTab.tsx):
 * trzyma stan ustawień, pytania, filtra dokumentów i strony, mapuje go na propsy kart
 * `SettingsCard` (T2) i `ResultsCard` (T3) i woła mutację wyszukiwania.
 * DEC-144: lista dokumentów filtra pochodzi z `doc_aggs` ostatniego wyniku BEZ filtra,
 * a zmiana filtra ponawia żądanie z `document_ids` od strony 1.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useTranslation } from 'react-i18next'
import Grid from '@mui/material/Grid'

import useNotifications from '../../../hooks/useNotifications/useNotifications'

import { useRerankOptions, useRetrieval } from './queries'
import type { DocAgg, RetrievalResult } from './queries'
import { ResultsCard } from './ResultsCard'
import { DEFAULT_SETTINGS, isMetaFilterActive } from './schema'
import type { RetrievalSettings } from './schema'
import { SettingsCard } from './SettingsCard'

export type RetrievalTabProps = {
  datasetId: string
}

/** Ostatnie „Uruchom” — pytanie i ustawienia, na których opierają się zmiany filtra i strony. */
type LastQuery = { question: string; settings: RetrievalSettings }

export function RetrievalTab(props: RetrievalTabProps): JSX.Element {
  const { datasetId } = props
  const { t } = useTranslation()
  const notifications = useNotifications()

  const [settings, setSettings] = useState<RetrievalSettings>(DEFAULT_SETTINGS)
  const [question, setQuestion] = useState('')
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [page, setPage] = useState(1)
  const [lastQuery, setLastQuery] = useState<LastQuery | null>(null)
  const [result, setResult] = useState<RetrievalResult | undefined>(undefined)
  const [allDocs, setAllDocs] = useState<DocAgg[]>([])

  const retrieval = useRetrieval()
  const rerankOptions = useRerankOptions()

  const showError = () => {
    notifications.show(t('retrieval.error'), { severity: 'error' })
  }

  const onSuccess = (data: RetrievalResult) => {
    setResult(data)
  }

  /** Uruchomienie od zera: bez filtra i od pierwszej strony; lista dokumentów z tego wyniku. */
  const run = () => {
    const asked = question.trim()
    setSelectedDocIds([])
    setPage(1)
    setLastQuery({ question: asked, settings })
    retrieval.mutate(
      { datasetId, question: asked, settings, page: 1 },
      {
        onSuccess: (data) => {
          setResult(data)
          setAllDocs(data.doc_aggs)
        },
        onError: showError,
      },
    )
  }

  /** Ponowienie ostatniego zapytania z nowym filtrem dokumentów i/lub stroną. */
  const requery = (documentIds: string[], nextPage: number) => {
    if (lastQuery === null) return
    retrieval.mutate(
      {
        datasetId,
        question: lastQuery.question,
        settings: lastQuery.settings,
        page: nextPage,
        documentIds,
      },
      { onSuccess, onError: showError },
    )
  }

  const handleDocsChange = (ids: string[]) => {
    setSelectedDocIds(ids)
    setPage(1)
    requery(ids, 1)
  }

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage)
    requery(selectedDocIds, nextPage)
  }

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 5 }}>
        <SettingsCard
          settings={settings}
          question={question}
          running={retrieval.isPending}
          rerankOptions={rerankOptions}
          datasetId={datasetId}
          onSettingsChange={setSettings}
          onQuestionChange={setQuestion}
          onRun={run}
        />
      </Grid>
      <Grid size={{ xs: 12, md: 7 }}>
        <ResultsCard
          result={result}
          loading={retrieval.isPending}
          allDocs={allDocs}
          selectedDocIds={selectedDocIds}
          page={page}
          pageSize={lastQuery?.settings.topN ?? settings.topN}
          // Filtr z ostatniego uruchomienia (jak `pageSize`): zmiana warunku bez ponownego
          // uruchomienia nie zmienia opisu pokazanego wyniku.
          filterActive={isMetaFilterActive(
            lastQuery?.settings.metaDataFilter ?? settings.metaDataFilter,
          )}
          onDocsChange={handleDocsChange}
          onPageChange={handlePageChange}
        />
      </Grid>
    </Grid>
  )
}
