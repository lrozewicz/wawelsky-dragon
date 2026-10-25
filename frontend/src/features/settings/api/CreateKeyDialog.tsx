/**
 * Dialog tworzenia klucza API (brief E3-6c1 T4 pkt 3; usterka U2 z odbioru E5-H5): opcjonalna
 * nazwa, a po sukcesie pełny token pokazywany dokładnie raz z ostrzeżeniem i przyciskiem
 * kopiowania. Token istnieje wyłącznie w `mutation.data` (kontrakt §2) — stan mutacji czyścimy
 * przy zamknięciu i przy odmontowaniu, więc ponowne otwarcie dialogu tokenu już nie pokazuje.
 *
 * Dialog ma dwa widoki (DEC-254). Dopóki nie ma tokenu, widoczny jest widok tworzenia (pole
 * nazwy + „Utwórz”); po sukcesie widok tworzenia ZNIKA, a zostaje sam widok sekretu. Duplikat
 * klucza przy dblclick (U2) blokuje strażnik synchroniczny (`submitted`), bo `isPending`
 * z hooka odświeża się dopiero po przelaniu stanu Reacta.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { useCreateToken } from '../queries'
import { copyToClipboard, selectElementContents } from './copyToClipboard'
import { copyErrorSx } from './copyErrorSx'

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export type CreateKeyDialogProps = {
  open: boolean
  onClose: () => void
}

export function CreateKeyDialog(props: CreateKeyDialogProps): JSX.Element {
  const { open, onClose } = props
  const { t } = useTranslation()
  const createToken = useCreateToken()
  const [name, setName] = useState('')
  const [copied, setCopied] = useState(false)
  // Porażka kopiowania (defekt MAJOR z QA-UI E6-2-2): bez tego dialog milczał, a token
  // pozostawał tylko na ekranie — użytkownik nie wiedział, że schowek nie dostarczył sekretu.
  const [copyFailed, setCopyFailed] = useState(false)
  const token = createToken.data?.token
  const reset = createToken.reset
  // Strażnik synchroniczny wysyłki (U2): ref zmienia się od razu, w odróżnieniu od `isPending`.
  const submitted = useRef(false)
  // Element z pełnym tokenem — przy porażce kopiowania zaznaczany do ręcznej kopii (Ctrl+C).
  const tokenRef = useRef<HTMLElement | null>(null)

  // Token żyje tylko w `mutation.data` — czyścimy stan mutacji też przy odmontowaniu dialogu.
  useEffect(() => () => reset(), [reset])

  /** Zamknięcie czyści pole, znaczniki kopiowania i stan mutacji tworzenia. */
  function close(): void {
    setName('')
    setCopied(false)
    setCopyFailed(false)
    submitted.current = false
    reset()
    onClose()
  }

  function create(): void {
    // Strażnik synchroniczny: dwa kliknięcia w tej samej klatce (dblclick) nie wyślą dwóch
    // żądań (U2) — `isPending` jest wtedy jeszcze nieodświeżony.
    if (submitted.current) return
    submitted.current = true
    setCopied(false)
    setCopyFailed(false)
    const trimmed = name.trim()
    createToken.mutate(
      { name: trimmed === '' ? undefined : trimmed },
      // Po zakończeniu (sukces albo błąd) zwalniamy strażnik: kolejny klucz da się utworzyć,
      // a po błędzie ponowić próbę.
      {
        onSettled: () => {
          submitted.current = false
        },
      },
    )
  }

  async function copyToken(): Promise<void> {
    if (token === undefined) return
    // „Skopiowano” wyłącznie po udanej kopii (brief E6-2 T7); przy porażce czytelny błąd
    // i token zaznaczony do ręcznego skopiowania (spójnie z kartą „Serwer MCP”).
    const ok = await copyToClipboard(token)
    setCopied(ok)
    setCopyFailed(!ok)
    if (!ok) selectElementContents(tokenRef.current)
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('settings.keys.createTitle')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {createToken.isError ? (
            <Alert severity="error">
              {errorText(createToken.error, t('settings.error.title'), t('settings.keys.error'))}
            </Alert>
          ) : null}

          {token === undefined ? (
            // M1 (QA E5-H9-2): fokus po otwarciu dialogu od razu w polu nazwy (wzorzec MUI:
            // `autoFocus` na polu wewnątrz `Dialog`). Limit 128 znaków = walidacja backendu;
            // licznik „{n}/128” pokazuje, ile jeszcze zostało (V12-3 T2, SC-V12-01).
            <TextField
              autoFocus
              size="small"
              label={t('settings.keys.name')}
              value={name}
              onChange={(event) => setName(event.target.value)}
              slotProps={{ htmlInput: { maxLength: 128 } }}
              helperText={t('settings.keys.nameCounter', { n: name.length })}
            />
          ) : (
            <Alert severity="warning">
              <Stack spacing={1}>
                <Typography variant="body2">{t('settings.keys.tokenOnce')}</Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <Box
                    ref={tokenRef}
                    component="code"
                    data-testid="settings-new-token"
                    sx={{ wordBreak: 'break-all' }}
                  >
                    {token}
                  </Box>
                  {/* flexShrink: 0 — wąski ekran ściskał przycisk do `min-width` (64 px), przez co
                      jednowyrazowe „Skopiowano” wystawało poza jego ramkę (defekt z zrzutu 390). */}
                  <Button size="small" sx={{ flexShrink: 0 }} onClick={() => void copyToken()}>
                    {copied ? t('settings.common.copied') : t('settings.keys.copyToken')}
                  </Button>
                </Stack>
                {copyFailed ? (
                  <Typography
                    variant="body2"
                    sx={copyErrorSx}
                    role="alert"
                    data-testid="settings-copy-error"
                  >
                    {t('settings.common.copyFailed')}
                  </Typography>
                ) : null}
              </Stack>
            </Alert>
          )}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('settings.common.close')}</Button>
        {token === undefined ? (
          <Button
            variant="contained"
            loading={createToken.isPending}
            disabled={createToken.isPending}
            onClick={create}
          >
            {t('settings.keys.submit')}
          </Button>
        ) : null}
      </DialogActions>
    </Dialog>
  )
}
