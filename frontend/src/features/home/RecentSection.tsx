/**
 * Sekcja „ostatnie zasoby” na stronie Home (08 §7.2): nagłówek z opcjonalną kontrolką,
 * rząd kart oraz wspólne stany: ładowanie (szkielety), błąd z „Ponów” i stan pusty.
 * Zawartość kart dostarcza wołający (`renderItem`), bo datasety i czaty mają inne kształty.
 */

import { Fragment } from 'react'
import type { ReactNode } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

/** Liczba szkieletów w stanie ładowania (odpowiada `RECENT_LIMIT`). */
const SKELETON_COUNT = 4

export type RecentSectionProps<T> = {
  /** Identyfikator sekcji dla testów (`within(getByTestId(...))`). */
  testId: string
  title: string
  items: T[] | undefined
  isPending: boolean
  isError: boolean
  onRetry: () => void
  /** Zawartość pokazywana, gdy lista jest pusta lub jeszcze nie dotyczy tej zakładki. */
  empty: ReactNode
  /** Karta „Zobacz wszystkie” dopinana do rzędu; brak = nie pokazuj. */
  seeAll?: ReactNode
  renderItem: (item: T) => ReactNode
  /** Dodatkowa kontrolka w nagłówku (np. przełącznik Chat | Search). */
  action?: ReactNode
}

export function RecentSection<T>(props: RecentSectionProps<T>) {
  const { t } = useTranslation()
  const { testId, title, items, isPending, isError, onRetry, empty, seeAll, renderItem, action } =
    props

  let body: ReactNode
  if (isPending) {
    body = (
      <Stack direction="row" spacing={2} data-testid="recent-loading">
        {Array.from({ length: SKELETON_COUNT }, (_, index) => (
          <Skeleton key={index} variant="rounded" height={120} sx={{ flex: 1 }} />
        ))}
      </Stack>
    )
  } else if (isError) {
    body = (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={onRetry}>
            {t('home.retry')}
          </Button>
        }
      >
        {t('home.error')}
      </Alert>
    )
  } else if (items === undefined || items.length === 0) {
    body = empty
  } else {
    body = (
      <Stack direction="row" spacing={2} sx={{ overflowX: 'auto', pb: 1 }}>
        {items.map((item, index) => (
          <Fragment key={index}>{renderItem(item)}</Fragment>
        ))}
        {seeAll}
      </Stack>
    )
  }

  return (
    <Stack spacing={2} data-testid={testId}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h5">{title}</Typography>
        {action}
      </Stack>
      {body}
    </Stack>
  )
}
