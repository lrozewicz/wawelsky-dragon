import type { JSX } from 'react'
import CircularProgress from '@mui/material/CircularProgress'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

/**
 * Ekran przejściowy powrotu z dostawcy tożsamości (08 §5.2). `beforeLoad` trasy albo przekierowuje
 * dalej, albo zatrzymuje się na `/login`, więc spinner widać tylko w czasie odtwarzania sesji.
 */
export function CallbackPage(): JSX.Element {
  const { t } = useTranslation()

  return (
    <Stack
      direction="column"
      sx={{ minHeight: '100dvh', alignItems: 'center', justifyContent: 'center' }}
    >
      <CircularProgress aria-label={t('auth.callback.loading')} />
    </Stack>
  )
}
