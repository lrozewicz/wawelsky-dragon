/**
 * Chip cytowania (08 §7.7, kontrakt WP E5-H3 §Decyzje UX #7): numer `[ID:n]` w treści odpowiedzi
 * asystenta staje się chipem, który po kliknięciu (albo Enter/Space) otwiera modalny `Dialog`
 * z pełnym źródłem: nazwą dokumentu (nagłówek), numerem strony gdy jest, PEŁNĄ treścią chunku
 * (bez przycinania; przewijaną w `maxHeight` ≤ 60vh, żeby cały dialog mieścił się nawet
 * w viewporcie 390×844), podobieństwem oraz przyciskami „Otwórz dokument" (woła istniejące
 * `onOpenDocument(docId, docName)` i zamyka dialog) i „Zamknij".
 *
 * Esc zamyka dialog, a fokus wraca na chip (domyślne zachowanie MUI `Dialog`). Hover i focus
 * NIE otwierają niczego — chip otwiera wyłącznie klik/Enter/Space (modal zastąpił dawany Popper).
 */

import { useId, useState } from 'react'
import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { Citation } from '../../chat-stream/reducer'

export type CitationChipProps = {
  index: number
  citation: Citation
  onOpenDocument: (docId: string, docName: string) => void
}

export function CitationChip(props: CitationChipProps): JSX.Element {
  const { index, citation, onOpenDocument } = props
  const { t } = useTranslation()
  const label = t('chat.cite.label', { n: index + 1 })
  const [open, setOpen] = useState(false)
  // Nagłówek dokumentu jest etykietą dialogu (kontrakt: `aria-labelledby` = nazwa dokumentu).
  const titleId = useId()

  return (
    <>
      <Chip
        component="button"
        size="small"
        label={index + 1}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        aria-labelledby={titleId}
        maxWidth="sm"
        fullWidth
      >
        {/* `overflow-wrap: anywhere`: długa nazwa pliku bez spacji zawija się zamiast przelewać
            się poza tytuł na wąskim viewporcie (QA-UI V13-z-2, MAJOR wizualny na 390 px). */}
        <DialogTitle id={titleId} sx={{ overflowWrap: 'anywhere' }}>
          {citation.docName}
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5}>
            {citation.page == null ? null : (
              <Typography variant="subtitle2" color="text.secondary">
                {t('chat.cite.page', { n: citation.page })}
              </Typography>
            )}
            {/* Pełny fragment bez przycinania; przewijany w `maxHeight` ≤ 60vh, żeby cały dialog
                zmieścił się w viewporcie 390×844 (kontrakt WP E5-H3 §Decyzje UX #7).
                `tabIndex=0` na przewijanym obszarze: axe `scrollable-region-focusable` wymaga,
                by użytkownik klawiatury mógł przewinąć przepełnioną treść. */}
            <Typography
              variant="body2"
              tabIndex={0}
              data-testid="cite-content"
              sx={{ whiteSpace: 'pre-wrap', maxHeight: '60vh', overflowY: 'auto' }}
            >
              {citation.content}
            </Typography>
            {citation.similarity === null ? null : (
              <Typography variant="caption" color="text.secondary">
                {t('chat.cite.similarity', { percent: Math.round(citation.similarity * 100) })}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>{t('chat.cite.close')}</Button>
          <Button
            variant="contained"
            onClick={() => {
              onOpenDocument(citation.docId, citation.docName)
              setOpen(false)
            }}
          >
            {t('chat.cite.open')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
