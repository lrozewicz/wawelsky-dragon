/**
 * Podpowiedź nad listą plików: „Poczekaj, aż pliki zostaną sparsowane…” — tylko gdy jakiś plik
 * jest w kolejce albo się parsuje; przy samych plikach ze statusem Sukces (albo bez plików)
 * wprowadzałaby w błąd (SC-E67-z2-07).
 */
import type { JSX } from 'react'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { parsingState } from './parsingState'
import type { DocumentRow } from './queries'

export function FilesSubtitle(props: { docs: DocumentRow[] }): JSX.Element | null {
  const { t } = useTranslation()
  const waiting = props.docs.some((doc) => {
    const state = parsingState(doc)
    return state === 'queued' || state === 'running'
  })
  if (!waiting) return null
  return (
    <Typography variant="body2" color="text.secondary">
      {t('datasets.files.subtitle')}
    </Typography>
  )
}
