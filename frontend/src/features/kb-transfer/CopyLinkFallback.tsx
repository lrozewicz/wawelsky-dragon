/**
 * Odmowa schowka przy „Kopiuj link” (SC-E67-05): komunikat błędu + pole tylko-do-odczytu
 * z adresem pobierania, zaznaczone od razu — użytkownik skopiuje je ręcznie (Ctrl+C).
 */

import { useEffect, useRef } from 'react'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { copyErrorSx } from '../settings/api/copyErrorSx'

export function CopyLinkFallback(props: { url: string }) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.select()
  }, [props.url])

  return (
    <>
      <Typography variant="caption" role="alert" sx={copyErrorSx}>
        {t('kbTransfer.bar.copyFailed')}
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={props.url}
        inputRef={inputRef}
        onFocus={(event) => event.target.select()}
        slotProps={{
          input: { readOnly: true },
          htmlInput: { 'aria-label': t('kbTransfer.bar.copyFallbackLabel') },
        }}
        data-testid="kb-copy-link-field"
      />
    </>
  )
}
