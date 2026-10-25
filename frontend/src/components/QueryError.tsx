/**
 * Wspólny komunikat błędu zapytania (kontrakt WP E3-7 §C6): `Alert severity="error"` z podanym
 * komunikatem i przyciskiem „Spróbuj ponownie” wołającym `onRetry` (zwykle `query.refetch`).
 * Używany przez listy i strony w miejsce dotychczasowych ad-hoc `Alert`-ów.
 */

import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import { useTranslation } from 'react-i18next'

export type QueryErrorProps = {
  message: string
  onRetry: () => void
}

export function QueryError(props: QueryErrorProps): JSX.Element {
  const { message, onRetry } = props
  const { t } = useTranslation()

  return (
    <Alert
      severity="error"
      data-testid="query-error"
      action={
        <Button color="inherit" size="small" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      }
    >
      {message}
    </Alert>
  )
}
