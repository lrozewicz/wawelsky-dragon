/**
 * Pozycja listy w dialogu przesyłania plików (wydzielona z `UploadDialog.tsx` przez limit rozmiaru
 * pliku): nazwa, rozmiar, etykieta stanu, przyczyna odrzucenia i pasek postępu. Pasek „Błąd” jest
 * czerwony i pełny (100 %) niezależnie od statusu HTTP (QA D2), „Przesłano” — 100 % w kolorze akcentu.
 */
import type { JSX } from 'react'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../../i18n'
import { formatBytes } from '../../../lib/format'
import { translateServerMessage } from '../../../lib/serverMessages'
import { doneMarkerColorSx } from '../../../theme/parsingStatus'
import type { UploadItem } from './uploadFiles'

/** Procent 0–100: „Przesłano” i „Błąd” = 100 %; bez zdarzeń postępu 0 (po ponowieniu `loaded` bywa stare). */
function itemPercent(item: UploadItem): number {
  if (item.state === 'done' || item.state === 'error') return 100
  return Math.round((item.total > 0 ? item.loaded / item.total : 0) * 100)
}

export function UploadItemRow(props: { item: UploadItem; index: number }): JSX.Element {
  const { item, index } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" noWrap sx={{ minWidth: 0, flex: 1 }}>
          {item.file.name}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {formatBytes(item.file.size, language)}
        </Typography>
        <Typography
          variant="caption"
          {...(item.state === 'done'
            ? { sx: doneMarkerColorSx } // D3: pary ≥ 4.5:1 zamiast success.main.
            : { color: 'text.secondary' })}
        >
          {t(`datasets.files.upload.${item.state}`)}
        </Typography>
      </Stack>
      {/* Przyczyna odrzucenia z koperty API, obok etykiety stanu (WP E5-H6a §C1); tłumaczenie
          komunikatu serwera przy WYŚWIETLENIU (T3b) — zmiana języka tłumaczy też istniejący wiersz. */}
      {item.state === 'error' && item.error !== undefined ? (
        <Typography variant="caption" color="error" role="alert">
          {item.errorCode === undefined
            ? item.error
            : translateServerMessage(item.errorCode, item.error, t)}
        </Typography>
      ) : null}
      <LinearProgress
        variant="determinate"
        value={itemPercent(item)}
        {...(item.state === 'error' ? { color: 'error' as const } : {})}
        aria-valuenow={itemPercent(item)}
        data-testid={`upload-progress-${index}`}
      />
    </Stack>
  )
}
