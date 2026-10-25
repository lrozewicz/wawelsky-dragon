/**
 * Karta „API serwera” (brief E3-6c1 T4 pkt 1): adres API w polu tylko do odczytu, przycisk
 * kopiowania ze znacznikiem „Skopiowano” wracającym po chwili oraz link do dokumentacji API
 * otwierany w nowej karcie. Kopiowanie idzie przez `copyToClipboard` (brief E6-2 T7): działa
 * też bez `navigator.clipboard` (HTTP), a porażka daje czytelny komunikat i zaznacza treść
 * pola do ręcznej kopii.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { copyToClipboard } from './copyToClipboard'
import { copyErrorSx } from './copyErrorSx'

/** Ile milisekund trzyma się znacznik „Skopiowano”. */
const COPIED_MS = 2000

/** Stan kopiowania: brak komunikatu / potwierdzenie / porażka. */
type CopyStatus = 'idle' | 'copied' | 'failed'

/** Adres API serwera widziany przez klientów zewnętrznych. */
function apiBaseUrl(): string {
  return `${window.location.origin}/api/v1`
}

export function ServerApiCard(): JSX.Element {
  const { t } = useTranslation()
  const [status, setStatus] = useState<CopyStatus>('idle')
  const inputRef = useRef<HTMLInputElement>(null)
  const url = apiBaseUrl()

  // Znacznik wraca do „Kopiuj” po chwili; komunikat porażki zostaje do kolejnej próby
  // (treść pola jest zaznaczona, więc instrukcja ręcznej kopii nie traci ważności).
  useEffect(() => {
    if (status !== 'copied') return
    const timer = setTimeout(() => setStatus('idle'), COPIED_MS)
    return () => clearTimeout(timer)
  }, [status])

  async function copy(): Promise<void> {
    const copiedNow = await copyToClipboard(url)
    if (copiedNow) {
      setStatus('copied')
    } else {
      // Porażka: treść pola zaznaczona od razu — użytkownik może nacisnąć Ctrl+C.
      inputRef.current?.select()
      setStatus('failed')
    }
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            {t('settings.keys.serverTitle')}
          </Typography>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1}
            sx={{ alignItems: { sm: 'center' } }}
          >
            <TextField
              size="small"
              fullWidth
              label={t('settings.keys.serverUrl')}
              value={url}
              inputRef={inputRef}
              slotProps={{ input: { readOnly: true } }}
            />
            <Button
              startIcon={<ContentCopyRoundedIcon />}
              aria-label={t('settings.keys.copyEndpoint')}
              onClick={() => void copy()}
            >
              {status === 'copied' ? t('settings.common.copied') : t('settings.common.copy')}
            </Button>
          </Stack>
          {status === 'failed' ? (
            <Typography variant="body2" sx={copyErrorSx} role="alert" data-testid="api-url-error">
              {t('settings.common.copyFailed')}
            </Typography>
          ) : null}
          <Typography variant="body2">
            <Link href="/api/docs" target="_blank" rel="noopener">
              {t('settings.keys.docs')}
            </Link>
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}
