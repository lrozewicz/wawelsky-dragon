/**
 * Wynik testu połączenia (kontrakt WP E4-3c §1, brief T3 p. 3): trzy kroki testu
 * (uwierzytelnienie, rozwiązanie witryny, dataset) z chipem ok/failed/skipped i szczegółem
 * błędu `*_error`, a przy rozwiązanym adresie — nazwa witryny oraz liczba i lista bibliotek.
 */

import type { JSX } from 'react'
import Chip from '@mui/material/Chip'
import type { ChipProps } from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { ConnectionTest } from './queries'

/** Znane wyniki kroku → klucz i18n (kontrakt §0); nieznany wynik traktujemy jak `failed`. */
const RESULT_KEYS: Record<string, string> = {
  ok: 'integrations.test.result.ok',
  failed: 'integrations.test.result.failed',
  skipped: 'integrations.test.result.skipped',
}

/** Kolory chipów wyników — jak `StatusChip` (kontrakt §1). */
const RESULT_COLORS: Record<string, ChipProps['color']> = {
  ok: 'success',
  failed: 'error',
  skipped: 'default',
}

type TestStepProps = {
  /** Nazwa kroku z `ConnectionTest` — trafia też do `data-testid`. */
  step: string
  labelKey: string
  status: string
  detail?: string | null | undefined
}

function TestStep(props: TestStepProps): JSX.Element {
  const { t } = useTranslation()
  const known = props.status in RESULT_KEYS ? props.status : 'failed'
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{ alignItems: 'center' }}
      data-testid={`integration-test-${props.step}`}
    >
      <Typography variant="body2" sx={{ minWidth: 180 }}>
        {t(props.labelKey)}
      </Typography>
      <Chip
        size="small"
        color={RESULT_COLORS[known]}
        label={t(RESULT_KEYS[known] ?? 'integrations.test.result.failed')}
      />
      {props.detail ? (
        <Typography variant="caption" color="text.secondary">
          {props.detail}
        </Typography>
      ) : null}
    </Stack>
  )
}

export function ConnectionTestResult(props: { result: ConnectionTest }): JSX.Element {
  const { t } = useTranslation()
  const { result } = props
  // Lista bibliotek przychodzi tylko po rozwiązaniu witryny; brak nazw = brak wiersza.
  const drives = result.drive_names ?? null

  return (
    <Stack spacing={1} data-testid="integration-test-result">
      <TestStep
        step="graph_auth"
        labelKey="integrations.test.graphAuth"
        status={result.graph_auth}
        detail={result.graph_auth_error}
      />
      <TestStep
        step="site_resolution"
        labelKey="integrations.test.siteResolution"
        status={result.site_resolution}
        detail={result.site_resolution_error}
      />
      <TestStep
        step="dataset_exists"
        labelKey="integrations.test.datasetExists"
        status={result.dataset_exists}
        // Schemat `ConnectionTest` nie ma `dataset_exists_error` — jest tylko nazwa celu (kontrakt §0).
        detail={result.dataset_name}
      />
      {result.site_display_name ? (
        <Typography variant="body2">
          {t('integrations.test.site', { name: result.site_display_name })}
        </Typography>
      ) : null}
      {drives === null ? null : (
        <Typography variant="body2">
          {t('integrations.test.drives', {
            names: drives.join(', '),
            visible: result.drives_visible ?? 0,
            after: result.drives_after_exclusion ?? 0,
          })}
        </Typography>
      )}
    </Stack>
  )
}
