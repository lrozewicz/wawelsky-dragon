/**
 * Dialog kluczy API użytkownika (kontrakt WP E3-6c2 §4 i §T4 pkt 5): lista kluczy z
 * `apiKeysQueryOptions`, tworzenie (`useCreateApiKey`) i usuwanie (`useDeleteApiKey`). Błąd pobrania
 * listy (`keys.isError`, kontrakt WP E3-H2b §C2) pokazujemy jako `Alert` zamiast tabeli. Pełny token
 * istnieje wyłącznie w `mutation.data` — pokazujemy go raz, nad listą, i czyścimy stan mutacji przy
 * zamknięciu oraz odmontowaniu dialogu, żeby po ponownym otwarciu tokenu już nie było.
 * Pole daty wygaśnięcia (WP E3-H2b §C1, K14 §3) jest opcjonalne: puste pomija `expires_at`,
 * a data nieprzyszła blokuje wysyłkę i pokazuje `expiresPast`.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'
import { copyToClipboard, selectElementContents } from '../../settings/api/copyToClipboard'
import { copyErrorSx } from '../../settings/api/copyErrorSx'
import type { ApiKey, WdUser } from '../queries'
import { apiKeysQueryOptions, useCreateApiKey, useDeleteApiKey } from '../queries'
import { wdErrorKey } from '../wdClient'

export type ApiKeysDialogProps = {
  user: WdUser
  open: boolean
  onClose: () => void
}

/** Data ISO 8601 w języku interfejsu; brak wartości to kreska. */
function formatDate(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

/** Puste pole daty nie jest błędem; wartość nieprzyszła (albo nieparsowalna) jest. */
function isPastDate(value: string): boolean {
  if (value === '') return false
  const at = new Date(value).getTime()
  return !Number.isFinite(at) || at <= Date.now()
}

/** Komórka „Wygasa”: brak daty = bezterminowy, data z przeszłości = wygasł, inaczej data. */
function formatExpiry(
  value: string | null,
  never: string,
  expired: string,
  language: string,
): string {
  if (value === null) return never
  const at = new Date(value)
  // K14 §3: klucz wygasa w chwili `expires_at`, więc próg to `<=`.
  return at.getTime() <= Date.now() ? expired : at.toLocaleString(language)
}

export function ApiKeysDialog(props: ApiKeysDialogProps): JSX.Element {
  const { user, open, onClose } = props
  const { t, i18n } = useTranslation()
  const keys = useQuery(apiKeysQueryOptions(user.id))
  const createKey = useCreateApiKey(user.id)
  const deleteKey = useDeleteApiKey(user.id)
  const [name, setName] = useState('')
  const [expires, setExpires] = useState('')
  const [expiresPast, setExpiresPast] = useState(false)
  const [copied, setCopied] = useState(false)
  // Porażka kopiowania (SC-E5-H9-08): czytelny komunikat zamiast milczenia, token zaznaczony
  // do ręcznej kopii (Ctrl+C).
  const [copyFailed, setCopyFailed] = useState(false)
  const token = createKey.data?.token
  const resetCreateKey = createKey.reset
  // Element z pełnym tokenem — przy porażce kopiowania zaznaczany (Selection API).
  const tokenRef = useRef<HTMLElement | null>(null)

  // Token żyje tylko w `mutation.data` — czyścimy stan mutacji też przy odmontowaniu dialogu.
  useEffect(() => () => resetCreateKey(), [resetCreateKey])

  /** Zamknięcie czyści pole, znacznik „Skopiowano” i stan mutacji tworzenia. */
  /** Zmiana pola daty: zerujemy błąd i liczymy go od nowa (walidacja w zdarzeniu, nie w renderze). */
  function changeExpires(value: string): void {
    setExpires(value)
    setExpiresPast(isPastDate(value))
  }

  function close(): void {
    setName('')
    setExpires('')
    setExpiresPast(false)
    setCopied(false)
    setCopyFailed(false)
    resetCreateKey()
    onClose()
  }

  function create(): void {
    // Data z przeszłości to błąd klienta — nie wysyłamy (K14 §3 p. 1 i tak odrzuciłoby ją 400).
    if (isPastDate(expires)) {
      setExpiresPast(true)
      return
    }
    setCopied(false)
    setCopyFailed(false)
    const trimmed = name.trim()
    createKey.mutate({
      name: trimmed === '' ? undefined : trimmed,
      expires_at: expires === '' ? undefined : new Date(expires).toISOString(),
    })
  }

  // Kopiowanie przez `copyToClipboard` (brief E6-2 T9): działa też bez `navigator.clipboard`
  // (HTTP); „Skopiowano” wyłącznie po udanej kopii, porażka — komunikat i zaznaczony token.
  async function copyToken(): Promise<void> {
    if (token === undefined) return
    const ok = await copyToClipboard(token)
    setCopied(ok)
    setCopyFailed(!ok)
    if (!ok) selectElementContents(tokenRef.current)
  }

  const items: ApiKey[] = keys.data ?? []

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="md">
      <DialogTitle>{t('admin.users.keys.title', { email: user.email })}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {createKey.isError ? (
            <Alert severity="error">{t(wdErrorKey(createKey.error))}</Alert>
          ) : null}
          {deleteKey.isError ? (
            <Alert severity="error">{t(wdErrorKey(deleteKey.error))}</Alert>
          ) : null}

          {token === undefined ? null : (
            <Alert severity="warning">
              <Stack spacing={1}>
                <Typography variant="body2">{t('admin.users.keys.tokenOnce')}</Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <Box
                    ref={tokenRef}
                    component="code"
                    data-testid="admin-key-token"
                    sx={{ wordBreak: 'break-all' }}
                  >
                    {token}
                  </Box>
                  {/* flexShrink: 0 — wąski ekran ściskał przycisk do `min-width` (64 px), przez co
                      jednowyrazowa etykieta „Skopiowano” wystawała poza jego ramkę. */}
                  <Button size="small" sx={{ flexShrink: 0 }} onClick={() => void copyToken()}>
                    {copied ? t('admin.users.keys.copied') : t('admin.users.keys.copy')}
                  </Button>
                </Stack>
                {copyFailed ? (
                  <Typography
                    variant="body2"
                    sx={copyErrorSx}
                    role="alert"
                    data-testid="admin-copy-error"
                  >
                    {t('settings.common.copyFailed')}
                  </Typography>
                ) : null}
              </Stack>
            </Alert>
          )}

          <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
            <TextField
              size="small"
              label={t('admin.users.keys.name')}
              value={name}
              onChange={(event) => setName(event.target.value)}
              sx={{ flexGrow: 1 }}
            />
            <TextField
              size="small"
              type="datetime-local"
              label={t('admin.users.keys.expires')}
              data-testid="admin-key-expires"
              slotProps={{ inputLabel: { shrink: true } }}
              value={expires}
              onChange={(event) => changeExpires(event.target.value)}
              error={expiresPast}
              helperText={expiresPast ? t('admin.users.keys.expiresPast') : undefined}
            />
            <Button variant="contained" loading={createKey.isPending} onClick={create}>
              {t('admin.users.keys.create')}
            </Button>
          </Stack>

          {keys.isError ? (
            // Kontrakt WP E3-7 §C6: błąd listy pokazuje `QueryError` z ponowieniem zamiast tabeli.
            <QueryError message={t('admin.common.loadError')} onRetry={() => void keys.refetch()} />
          ) : keys.isPending ? (
            <Typography variant="body2" color="text.secondary">
              {t('admin.common.loading')}
            </Typography>
          ) : items.length === 0 ? (
            <EmptyState title={t('admin.users.keys.empty')} />
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('admin.users.keys.col.name')}</TableCell>
                    <TableCell>{t('admin.users.keys.col.prefix')}</TableCell>
                    <TableCell>{t('admin.users.keys.col.created')}</TableCell>
                    <TableCell>{t('admin.users.keys.col.lastUsed')}</TableCell>
                    <TableCell>{t('admin.users.keys.col.expires')}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((key) => (
                    <TableRow key={key.id}>
                      <TableCell>{key.name ?? '—'}</TableCell>
                      <TableCell>{key.prefix}</TableCell>
                      <TableCell>{formatDate(key.created_at, i18n.language)}</TableCell>
                      <TableCell>{formatDate(key.last_used_at, i18n.language)}</TableCell>
                      <TableCell>
                        {formatExpiry(
                          key.expires_at,
                          t('admin.users.keys.never'),
                          t('admin.users.keys.expired'),
                          i18n.language,
                        )}
                      </TableCell>
                      <TableCell>
                        <IconButton
                          size="small"
                          aria-label={t('admin.users.keys.delete')}
                          onClick={() => deleteKey.mutate(key.id)}
                        >
                          <DeleteOutlineRoundedIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('admin.common.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
