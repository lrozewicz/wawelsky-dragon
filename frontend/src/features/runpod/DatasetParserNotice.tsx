/**
 * Podpowiedź w oknie „model jest wyłączony”: pliki mają zapisany inny parser niż konfiguracja zbioru
 * (zmiana konfiguracji nie objęła plików wgranych wcześniej). Przycisk przepina wskazane pliki na
 * parser zbioru i uruchamia parsowanie od nowa, więc następne pytanie dotyczy już właściwego modelu.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import { useTranslation } from 'react-i18next'

import { api, apiCall } from '../../api/client'
import { listAllDocuments } from '../datasets/config/applyToDocuments'
import { useParseDocuments } from '../datasets/files/mutations'
import { closeRunpodPrompt } from './promptStore'
import type { RunpodPrompt } from './promptStore'

async function switchParser(prompt: RunpodPrompt, parser: string): Promise<void> {
  const { datasetId, documentIds } = prompt
  const documents = await listAllDocuments(datasetId)
  for (const doc of documents.filter((row) => documentIds.includes(row.id))) {
    // Pełna konfiguracja pliku: PATCH bez `raptor` skasowałby jego ustawienia RAPTOR-a.
    await apiCall(
      api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}', {
        params: { path: { dataset_id: datasetId, document_id: doc.id } },
        body: { parser_config: { ...doc.parser_config, layout_recognize: parser } },
      }),
    )
  }
}

export function DatasetParserNotice(props: { prompt: RunpodPrompt }): JSX.Element | null {
  const { prompt } = props
  const { t } = useTranslation()
  const parse = useParseDocuments(prompt.datasetId)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const parser = prompt.preflight.dataset_parser
  if (!parser) return null

  const apply = async (): Promise<void> => {
    setBusy(true)
    setFailed(false)
    try {
      await switchParser(prompt, parser)
      closeRunpodPrompt()
      await parse.mutateAsync({ ids: prompt.documentIds })
    } catch {
      setFailed(true)
      setBusy(false)
    }
  }

  return (
    <Alert
      severity={failed ? 'error' : 'info'}
      sx={{ mt: 2 }}
      data-testid="dataset-parser-notice"
      action={
        <Button
          color="inherit"
          size="small"
          disabled={busy}
          onClick={() => void apply()}
          data-testid="dataset-parser-use"
        >
          {t('runpod.prompt.useDatasetParser', { parser })}
        </Button>
      }
    >
      {t('runpod.prompt.datasetParser', { current: prompt.preflight.model ?? '', parser })}
    </Alert>
  )
}
