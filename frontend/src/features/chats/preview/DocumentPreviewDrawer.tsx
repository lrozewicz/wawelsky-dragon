/**
 * Szuflada podglądu dokumentu (08 §7.7 p. 2): `Drawer anchor="right"` o szerokości 560 px
 * (na węższych ekranach pełna szerokość — `maxWidth: '100%'`; MUI 9 nie ma już `PaperProps`,
 * stąd `slotProps.paper`, jak w `ChatSettingsDrawer`). Nagłówek niesie nazwę dokumentu
 * i przycisk zamknięcia; Esc oraz kliknięcie w tło zamykają szufladę przez `onClose`
 * (wbudowane zachowanie `Drawer`).
 *
 * Szuflada jest otwarta dokładnie wtedy, gdy `documentId !== null`, a `key={documentId}`
 * odmontowuje podgląd przy zmianie dokumentu — bez ręcznego czyszczenia stanu.
 */

import type { JSX } from 'react'
import CloseIcon from '@mui/icons-material/Close'
import Box from '@mui/material/Box'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { DocumentPreview } from './DocumentPreview'

export type DocumentPreviewDrawerProps = {
  documentId: string | null
  documentName?: string
  onClose: () => void
}

export function DocumentPreviewDrawer(props: DocumentPreviewDrawerProps): JSX.Element {
  const { documentId, documentName, onClose } = props
  const { t } = useTranslation()

  return (
    <Drawer
      anchor="right"
      open={documentId !== null}
      onClose={onClose}
      slotProps={{ paper: { sx: { width: 560, maxWidth: '100%' } } }}
    >
      <Stack sx={{ height: '100%' }}>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', justifyContent: 'space-between', p: 2, pb: 1 }}
        >
          <Typography variant="h6" noWrap>
            {documentName ?? t('chat.preview.title')}
          </Typography>
          <IconButton aria-label={t('chat.preview.close')} onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>
        <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', px: 2, pb: 2 }}>
          {documentId === null ? null : (
            <DocumentPreview key={documentId} documentId={documentId} documentName={documentName} />
          )}
        </Box>
      </Stack>
    </Drawer>
  )
}
