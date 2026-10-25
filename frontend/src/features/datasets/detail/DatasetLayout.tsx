/**
 * Layout szczegółów datasetu (08 §7.4, kontrakt WP E3-3a §T3): nagłówek z metadanymi, zakładki
 * i treść wybranej zakładki. Szczegół pochodzi z zapytania rozgrzanego loaderem trasy
 * (`ensureQueryData`), a nieudane wczytanie pokazuje `Alert` z powrotem do listy — ten sam
 * komponent (`DatasetLoadError`) renderuje `errorComponent` layoutu tras `/_app/dataset`.
 */

import type { JSX, ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link as RouterLink } from '@tanstack/react-router'
import Alert from '@mui/material/Alert'
import Container from '@mui/material/Container'
import useMediaQuery from '@mui/material/useMediaQuery'
import MuiLink from '@mui/material/Link'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { datasetQueryOptions } from '../queries'

import { DatasetHeader } from './DatasetHeader'
import { DatasetTabs } from './DatasetTabs'
import type { DatasetTabKey } from './DatasetTabs'

export type { DatasetTabKey } from './DatasetTabs'

export type DatasetLayoutProps = {
  datasetId: string
  activeTab: DatasetTabKey
  children: ReactNode
}

/** Komunikat nieudanego wczytania szczegółu: wspólny dla stanu zapytania i `errorComponent` tras. */
export function DatasetLoadError(): JSX.Element {
  const { t } = useTranslation()

  return (
    <Container maxWidth="lg">
      <Stack spacing={2} sx={{ my: 2 }}>
        <Alert severity="error">{t('datasets.detail.loadError')}</Alert>
        <MuiLink
          component={RouterLink}
          to="/datasets"
          underline="hover"
          sx={{ alignSelf: 'flex-start' }}
        >
          {t('datasets.detail.backToList')}
        </MuiLink>
      </Stack>
    </Container>
  )
}

export function DatasetLayout(props: DatasetLayoutProps): JSX.Element {
  const { datasetId, activeTab, children } = props
  const dataset = useQuery(datasetQueryOptions(datasetId))
  // QA E6-1b-1 (D2): przy 1600 px kolumna „Nazwa” kurczyła się do ~49 px, bo Container
  // maxWidth=lg zaciskał treść do ~1150 px przy 893 px kolumn stałych (T5a). Zakładki
  // przy ≥ 1536 px (jak kolumna „Metadane”) dostaje kontener xl; niżej maxWidth=lg — zachowanie
  // bez zmian (s18/s21/s24). E67-z2 T4: ten sam kontener dla WSZYSTKICH zakładek (przy 1600 px
  // Pliki zaczynały treść w x=264, Logi/Konfiguracja w x=344 — przeskok układu).
  // Uwaga: prop `maxWidth="xl"` w MUI v9 emituje tylko regułę min-width:1536 px (poniżej kontener fluid), więc o szerokości decyduje `useMediaQuery`.
  const wideFiles = useMediaQuery('(min-width:1536px)')

  if (dataset.isError) return <DatasetLoadError />

  return (
    <Container
      maxWidth={wideFiles ? 'xl' : 'lg'}
      sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}
    >
      <Stack spacing={2} sx={{ flex: 1, my: 2 }}>
        {dataset.isPending ? (
          <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
            <Skeleton variant="circular" width={64} height={64} />
            <Skeleton variant="text" width={240} height={40} />
          </Stack>
        ) : (
          <DatasetHeader dataset={dataset.data} />
        )}
        <DatasetTabs datasetId={datasetId} activeTab={activeTab} />
        <Stack sx={{ flex: 1 }}>{children}</Stack>
      </Stack>
    </Container>
  )
}
