/**
 * Zakładki szczegółów datasetu (08 §7.4, kontrakt WP E3-3a §T3): Pliki · Test retrievalu · Logi ·
 * Konfiguracja, w tej kolejności, jako linki do `/dataset/<zakładka>/$id`. Poniżej progu `md`
 * pasek przewija się poziomo (`scrollable`), wyżej mieści się w całości (`standard`).
 */

import type { JSX } from 'react'
import { Link } from '@tanstack/react-router'
import Tab from '@mui/material/Tab'
import type { TabProps } from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTranslation } from 'react-i18next'

export type DatasetTabKey = 'files' | 'retrieval' | 'logs' | 'configuration'

/** Kolejność zakładek z kontraktu §T3 (nie kolejność kluczy w `TAB_PATHS`). */
const TAB_ORDER: readonly DatasetTabKey[] = ['files', 'retrieval', 'logs', 'configuration']

/** Adresy tras zakładek — id tras z `routes/_app/dataset/*.$id.tsx`. */
const TAB_PATHS = {
  files: '/dataset/files/$id',
  retrieval: '/dataset/retrieval/$id',
  logs: '/dataset/logs/$id',
  configuration: '/dataset/configuration/$id',
} as const

/**
 * MUI normalizuje props `component` do generycznego `LinkComponent`, przez co `params` degeneruje
 * się do wariantu funkcyjnego `ParamsReducerFn` — rzutujemy więc same propsy linku-routera.
 */
function datasetTabLinkProps(key: DatasetTabKey, datasetId: string): TabProps {
  return {
    component: Link,
    to: TAB_PATHS[key],
    params: { id: datasetId },
  } as TabProps
}

export type DatasetTabsProps = {
  datasetId: string
  activeTab: DatasetTabKey
}

export function DatasetTabs(props: DatasetTabsProps): JSX.Element {
  const { datasetId, activeTab } = props
  const { t } = useTranslation()
  // jsdom nie zna `matchMedia` — MUI zwraca wtedy `defaultMatches` (false), czyli wariant `standard`.
  const belowMd = useMediaQuery((theme) => theme.breakpoints.down('md'))

  return (
    <Tabs
      value={activeTab}
      variant={belowMd ? 'scrollable' : 'standard'}
      aria-label={t('datasets.detail.tabsLabel')}
      sx={{ borderBottom: 1, borderColor: 'divider' }}
    >
      {TAB_ORDER.map((key) => (
        <Tab
          key={key}
          value={key}
          label={t(`datasets.detail.tab.${key}`)}
          {...datasetTabLinkProps(key, datasetId)}
        />
      ))}
    </Tabs>
  )
}
