/**
 * Karta „Serwer MCP" (brief E6-2 T4, makieta 08-frontend §7.11): adresy transportów MCP
 * liczone z origin strony, kopiowanie każdego z nich (znacznik „Skopiowano" wraca po chwili,
 * jak w `ServerApiCard`) oraz przykład konfiguracji klienta z placeholderem klucza — przykład
 * nigdy nie wstawia prawdziwego tokenu. Kopiowanie idzie przez `copyToClipboard` (brief
 * E6-2 T7): działa też bez `navigator.clipboard` (HTTP), a porażka daje czytelny komunikat
 * w miejscu potwierdzenia i zaznacza tekst do ręcznej kopii.
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX } from 'react'
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { copyToClipboard, selectElementContents } from './copyToClipboard'
import { copyErrorSx } from './copyErrorSx'

/** Ile milisekund trzyma się znacznik „Skopiowano”. */
const COPIED_MS = 2000

/** Który element karty ostatnio skopiowano (jeden znacznik/komunikat naraz). */
type CopiedWhat = 'http' | 'sse' | 'example'

/** Wynik ostatniej próby kopiowania: który element i czy się udała (`null` = brak komunikatu). */
type CopyStatus = { what: CopiedWhat; ok: boolean } | null

/** Adres transportu MCP widziany przez klientów zewnętrznych (origin strony + ścieżka). */
function mcpUrl(path: '/mcp' | '/sse'): string {
  return `${window.location.origin}${path}`
}

/** Przykład konfiguracji klienta MCP: placeholder klucza, nigdy prawdziwy token. */
function clientExample(httpUrl: string, keyPlaceholder: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        'wawelsky-dragon': {
          url: httpUrl,
          headers: { Authorization: `Bearer ${keyPlaceholder}` },
        },
      },
    },
    null,
    2,
  )
}

export function McpServerCard(): JSX.Element {
  const { t } = useTranslation()
  const [status, setStatus] = useState<CopyStatus>(null)
  const httpRef = useRef<HTMLParagraphElement | null>(null)
  const sseRef = useRef<HTMLParagraphElement | null>(null)
  const exampleRef = useRef<HTMLPreElement | null>(null)

  // Znacznik „Skopiowano” wraca do „Kopiuj” po chwili; komunikat porażki zostaje do kolejnej
  // próby (tekst jest zaznaczony, więc instrukcja ręcznej kopii nie traci ważności).
  // Efekt czyści timer przy każdej zmianie stanu, więc stara porażka nie skasuje nowego wyniku.
  useEffect(() => {
    if (status?.ok !== true) return
    const timer = setTimeout(() => setStatus(null), COPIED_MS)
    return () => clearTimeout(timer)
  }, [status])

  async function copy(what: CopiedWhat, text: string, target: HTMLElement | null): Promise<void> {
    const ok = await copyToClipboard(text)
    // Porażka: tekst zaznaczony od razu — użytkownik może nacisnąć Ctrl+C.
    if (!ok) selectElementContents(target)
    setStatus({ what, ok })
  }

  const httpUrl = mcpUrl('/mcp')
  const sseUrl = mcpUrl('/sse')
  const example = clientExample(httpUrl, t('settings.mcp.keyPlaceholder'))
  const buttonLabel = (what: CopiedWhat): string =>
    status?.what === what && status.ok ? t('settings.common.copied') : t('settings.common.copy')

  /** Czytelny błąd po porażce kopiowania `what` (w miejscu potwierdzenia „Skopiowano”). */
  const copyError = (what: CopiedWhat, testId: string): JSX.Element | null =>
    status?.what === what && !status.ok ? (
      <Typography variant="body2" sx={copyErrorSx} role="alert" data-testid={testId}>
        {t('settings.common.copyFailed')}
      </Typography>
    ) : null

  return (
    <Card variant="outlined" data-testid="mcp-card">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            {t('settings.mcp.title')}
          </Typography>
          <Typography variant="body2">{t('settings.mcp.description')}</Typography>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={{ xs: 0.5, sm: 2 }}
            sx={{ alignItems: { sm: 'center' } }}
          >
            <Typography
              variant="body2"
              sx={{ width: { sm: 140 }, flexShrink: 0, color: 'text.secondary' }}
            >
              {t('settings.mcp.httpLabel')}
            </Typography>
            {/* Długi adres: wielokropek + `title`, przycisk kopiowania zawsze widoczny. */}
            <Typography
              ref={httpRef}
              variant="body2"
              noWrap
              title={httpUrl}
              data-testid="mcp-url-http"
              sx={{ flex: 1, minWidth: 0 }}
            >
              {httpUrl}
            </Typography>
            <Button
              startIcon={<ContentCopyRoundedIcon />}
              aria-label={t('settings.mcp.copyHttp')}
              data-testid="mcp-copy-http"
              onClick={() => void copy('http', httpUrl, httpRef.current)}
            >
              {buttonLabel('http')}
            </Button>
          </Stack>
          {copyError('http', 'mcp-error-http')}
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={{ xs: 0.5, sm: 2 }}
            sx={{ alignItems: { sm: 'center' } }}
          >
            <Typography
              variant="body2"
              sx={{ width: { sm: 140 }, flexShrink: 0, color: 'text.secondary' }}
            >
              {t('settings.mcp.sseLabel')}
            </Typography>
            <Typography
              ref={sseRef}
              variant="body2"
              noWrap
              title={sseUrl}
              data-testid="mcp-url-sse"
              sx={{ flex: 1, minWidth: 0 }}
            >
              {sseUrl}
            </Typography>
            <Button
              startIcon={<ContentCopyRoundedIcon />}
              aria-label={t('settings.mcp.copySse')}
              data-testid="mcp-copy-sse"
              onClick={() => void copy('sse', sseUrl, sseRef.current)}
            >
              {buttonLabel('sse')}
            </Button>
          </Stack>
          {copyError('sse', 'mcp-error-sse')}
          <Stack spacing={0.5}>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: 'center', justifyContent: 'space-between' }}
            >
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                {t('settings.mcp.exampleLabel')}
              </Typography>
              <Button
                startIcon={<ContentCopyRoundedIcon />}
                aria-label={t('settings.mcp.copyExample')}
                data-testid="mcp-copy-example"
                onClick={() => void copy('example', example, exampleRef.current)}
              >
                {buttonLabel('example')}
              </Button>
            </Stack>
            {/* Przykład JSON zawija długie linie (QA E5-H9-2: na 390 px był ucięty na prawej
                krawędzi bez afordancji przewijania); tokeny motywu → czytelny też w ciemnym (U9). */}
            <Box
              ref={exampleRef}
              component="pre"
              data-testid="mcp-example"
              sx={[
                {
                  m: 0,
                  p: 1.5,
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                  typography: 'body2',
                  bgcolor: 'action.hover',
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 1,
                  color: 'text.primary',
                },
                // `pre` z UA ma własną czcionkę; przywracamy czytelną mono poza resetem MUI.
                { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' },
              ]}
            >
              {example}
            </Box>
            {copyError('example', 'mcp-error-example')}
          </Stack>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <InfoOutlinedIcon fontSize="small" color="secondary" sx={{ mt: '2px' }} />
            {/* Nota tekstowa (SC-E5-H9-08): odesłanie do runbooka bez martwego linku. */}
            <Typography
              variant="body2"
              sx={{ color: 'text.secondary' }}
              data-testid="mcp-runbook-note"
            >
              {t('settings.mcp.runbookNote')}
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}
