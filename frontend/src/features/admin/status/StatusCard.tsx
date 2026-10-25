/**
 * Wspólny szkielet karty statusu (kontrakt WP E3-6c2 §4): obramowana `Card` z nagłówkiem
 * poziomu `h2` oraz stanami ładowania (`Skeleton`) i błędu (`Alert`) wspólnymi dla wszystkich
 * kart. Karta zależna od kilku zapytań sama decyduje, co podać w `isLoading`/`isError`.
 */

import type { ReactNode } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type StatusCardProps = {
  /** `data-testid` karty — wiążący dla testów i e2e (kontrakt §4). */
  testId: string
  title: string
  isLoading: boolean
  isError: boolean
  children: ReactNode
}

export function StatusCard(props: StatusCardProps): JSX.Element {
  const { t } = useTranslation()

  return (
    <Card variant="outlined" data-testid={props.testId} sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={1.5}>
          <Typography component="h2" variant="h6">
            {props.title}
          </Typography>
          {props.isError ? (
            <Alert severity="error">{t('admin.status.cardError')}</Alert>
          ) : props.isLoading ? (
            <Skeleton variant="rounded" height={56} />
          ) : (
            props.children
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}
