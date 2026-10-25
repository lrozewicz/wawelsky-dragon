/**
 * Podgląd dokumentu (08 §7.7, §9.4) — komponent WIELOKROTNEGO UŻYTKU: szuflada czatu (ten WP)
 * i strona `/document/:id` (E3-3). Treść pobiera przez klienta API (Bearer + odświeżenie 401)
 * jako blob (`parseAs: 'blob'` — DEC-080), a sposób wyświetlenia wybiera z `Content-Type` blobu.
 *
 * Tekst dekodujemy `Blob.text()`, które zawsze interpretuje bajty jako UTF-8 — polskie znaki
 * działają mimo `charset` z nagłówka (§9.4). HTML z backendu (`derived/normalized.html`) ląduje
 * w `<iframe sandbox="">` bez żadnych uprawnień. Obrazy, PDF i typy nieobsługiwane idą przez
 * object URL, zwalniany w cleanupie efektu. Dla PDF prop `page` (liczba całkowita >= 1) dokłada
 * do adresu fragment `#page=N` — object URL powstaje raz, więc zmiana strony nie pobiera blobu
 * ponownie (kontrakt WP E3-H2a §K5).
 *
 * Błąd domenowy (brak dokumentu, cudzy dokument) przychodzi jako HTTP 200 z kopertą JSON
 * (K3 #3, `app/api/errors.py`) — rozpoznajemy ją po `Content-Type` i niezerowym `code`
 * (`jsonEnvelopeError`), bo przy `parseAs: 'blob'` nie ma jej w `error`.
 *
 * Typ bez podglądu (gałąź `other`, np. `.xlsx`) i blob pusty (0 B) dostają komunikat
 * „Podgląd niedostępny…” — `other` z linkiem „Pobierz”, pusty blob bez niego (DEC-357);
 * bez tego pusty blob renderuje pusty `<pre>` albo ramkę — biały prostokąt (SC-V12-09 k3).
 */

import { useEffect, useMemo, useState } from 'react'
import type { JSX } from 'react'
import { queryOptions, useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { api } from '../../../api/client'
import { ApiError, unwrap } from '../../../api/envelope'

export type DocumentPreviewProps = { documentId: string; documentName?: string; page?: number }

type PreviewKind = 'html' | 'text' | 'image' | 'pdf' | 'other'

/**
 * Fragment adresu object URL dla podglądu PDF (kontrakt WP E3-H2a §K5): `#page=N` tylko dla
 * liczby całkowitej >= 1 (przeglądarki nie rozumieją `#page=0` ani ułamków), inaczej nic.
 */
function pdfPageFragment(page: number | undefined): string {
  if (page === undefined || !Number.isInteger(page) || page < 1) return ''
  return `#page=${String(page)}`
}

/** Typ MIME bez parametrów (np. `text/plain; charset=utf-8` → `text/plain`). */
function mediaType(contentType: string): string {
  return contentType.split(';')[0]?.trim().toLowerCase() ?? ''
}

/** Rodzaj podglądu z nagłówka `Content-Type` blobu. */
function previewKind(contentType: string): PreviewKind {
  const media = mediaType(contentType)
  if (media === 'text/html') return 'html'
  if (media.startsWith('text/')) return 'text'
  if (media.startsWith('image/')) return 'image'
  if (media === 'application/pdf') return 'pdf'
  return 'other'
}

/**
 * Koperta błędu domenowego w ciele odpowiedzi albo `null`, gdy to zwykły plik. Backend przestrzeni
 * ragflow oddaje błędy domenowe jako HTTP 200 z JSON-em `{code, message}` (K3 #3, `app/api/errors.py`),
 * a przy `parseAs: 'blob'` taka koperta trafia do `data`, nie do `error`. `JSON.parse` może paść na
 * treści dowolnego dokumentu `.json` — wtedy zwracamy `null`, bo to plik do pokazania, nie błąd.
 */
function jsonEnvelopeError(body: string, httpStatus: number): ApiError | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(body)
  } catch {
    return null
  }
  if (parsed === null || typeof parsed !== 'object') return null
  const { code, message } = parsed as { code?: unknown; message?: unknown }
  if (typeof code !== 'number' || code === 0) return null
  return new ApiError(code, typeof message === 'string' ? message : '', httpStatus)
}

function previewQueryOptions(documentId: string) {
  return queryOptions({
    queryKey: ['documents', 'preview', documentId] as const,
    queryFn: async () => {
      const result = await api.GET('/api/v1/documents/{document_id}/preview', {
        params: { path: { document_id: documentId } },
        parseAs: 'blob',
      })
      // Błąd transportu/HTTP (401, 5xx): `unwrap` buduje `ApiError` z koperty błędu albo ze statusu.
      if (!result.response.ok) return unwrap<Blob>(result)

      // 204 oraz `Content-Length: 0` dają `data === undefined` (openapi-fetch 0.17) — pusty blob.
      const blob = result.data ?? new Blob()
      if (mediaType(blob.type) !== 'application/json') return blob

      const failure = jsonEnvelopeError(await blob.text(), result.response.status)
      if (failure === null) return blob
      throw failure
    },
  })
}

/** Komunikat błędu pobrania: treść z `ApiError`, a przy błędzie transportu — tekst z i18n. */
function previewError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message !== '') return error.message
  return fallback
}

/**
 * Komunikat „niedostępny” (DEC-357): gałąź `other` (typ bez podglądu) pokazuje go z linkiem
 * „Pobierz”; pusty blob (0 B — pusty plik albo pusta odpowiedź backendu) tylko sam komunikat,
 * bo nie ma czego pobierać. Bez tego pusty blob daje pusty `<pre>`/ramkę — biały prostokąt.
 */
function PreviewUnavailable(props: {
  documentName?: string
  objectUrl?: string | null
}): JSX.Element {
  const { t } = useTranslation()
  return (
    <Stack spacing={1} sx={{ alignItems: 'flex-start' }}>
      <Typography variant="body2" color="text.secondary">
        {t('chat.preview.unsupported')}
      </Typography>
      {props.objectUrl ? (
        <Link href={props.objectUrl} download={props.documentName}>
          {t('chat.preview.download')}
        </Link>
      ) : null}
    </Stack>
  )
}

function PreviewProgress(): JSX.Element {
  const { t } = useTranslation()

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
      <CircularProgress aria-label={t('chat.preview.loading')} />
    </Box>
  )
}

export function DocumentPreview(props: DocumentPreviewProps): JSX.Element {
  const { documentId, documentName, page } = props
  const { t } = useTranslation()
  const preview = useQuery(previewQueryOptions(documentId))

  const blob = preview.data
  const kind = blob === undefined ? null : previewKind(blob.type)
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    if (blob === undefined || (kind !== 'text' && kind !== 'html')) return
    let active = true
    void blob.text().then((value) => {
      if (active) setText(value)
    })
    return () => {
      active = false
    }
  }, [blob, kind])

  const objectUrl = useMemo(() => {
    if (blob === undefined) return null
    if (kind !== 'image' && kind !== 'pdf' && kind !== 'other') return null
    // Pusty blob nie ma treści — komponent pokaże komunikat (DEC-357), URL zbędny.
    if (blob.size === 0) return null
    return URL.createObjectURL(blob)
  }, [blob, kind])

  useEffect(() => {
    if (objectUrl === null) return
    return () => URL.revokeObjectURL(objectUrl)
  }, [objectUrl])

  if (preview.isError) {
    return (
      <Alert
        severity="error"
        action={<Button onClick={() => void preview.refetch()}>{t('chat.preview.retry')}</Button>}
      >
        {previewError(preview.error, t('chat.preview.loadError'))}
      </Alert>
    )
  }

  if (blob === undefined || kind === null) return <PreviewProgress />

  // Pusty blob (0 B) nie ma treści w żadnej gałęzi — komunikat zamiast pustego prostokąta
  // (SC-V12-09 k3, DEC-357).
  if (blob.size === 0) return <PreviewUnavailable />

  const label = documentName ?? t('chat.preview.title')

  switch (kind) {
    case 'html':
      // Bez `allow-scripts`/`allow-same-origin` — HTML backendu nie może niczego wykonać.
      return text === null ? (
        <PreviewProgress />
      ) : (
        <iframe
          title={label}
          sandbox=""
          srcDoc={text}
          style={{ width: '100%', height: '100%', border: 0 }}
        />
      )
    case 'text':
      return text === null ? (
        <PreviewProgress />
      ) : (
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{text}</pre>
      )
    case 'image':
      return objectUrl === null ? (
        <PreviewProgress />
      ) : (
        <img src={objectUrl} alt={label} style={{ maxWidth: '100%', height: 'auto' }} />
      )
    case 'pdf':
      return (
        <iframe
          title={label}
          src={objectUrl === null ? undefined : objectUrl + pdfPageFragment(page)}
          style={{ width: '100%', height: '100%', border: 0 }}
        />
      )
    default:
      return <PreviewUnavailable documentName={documentName} objectUrl={objectUrl} />
  }
}
