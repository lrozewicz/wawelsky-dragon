/**
 * Dialog „Odrzucić zmiany?” (SC-V12-07, makieta w work/wp/V12/SCENARIOS.md): treść nazywa
 * kontekst („Niezapisane zmiany w ustawieniach czatu zostaną utracone.”), „Wróć do edycji”
 * dostaje domyślny fokus i obsługują go Esc oraz klik w tło dialogu, „Odrzuć” jest w kolorze
 * błędu. Wspólny dla szuflad ustawień czatu, wyszukiwarki i metadanych pliku; stan otwarcia
 * trzyma `useDiscardGuard`.
 */

import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import { useTranslation } from 'react-i18next'

/** Szuflada, której dotyczą niezapisane zmiany — wybiera nazwę kontekstu w treści (i18n). */
export type DiscardContext = 'chat' | 'search' | 'metadata'

export type DiscardChangesDialogProps = {
  open: boolean
  context: DiscardContext
  /** „Wróć do edycji” — bez utraty zmian; także Esc i tło dialogu. */
  onKeep: () => void
  /** „Odrzuć” — porzuca zmiany i zamyka szufladę. */
  onDiscard: () => void
}

export function DiscardChangesDialog(props: DiscardChangesDialogProps) {
  const { open, context, onKeep, onDiscard } = props
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onKeep} maxWidth="xs" fullWidth>
      <DialogTitle>{t('common.discard.title')}</DialogTitle>
      <DialogContent>
        <DialogContentText>
          {t('common.discard.body', { context: t(`common.discard.context.${context}`) })}
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        {/* autoFocus: fokus startuje na „Wróć do edycji” (SC-V12-07 krok 1), Esc = ten przycisk. */}
        <Button autoFocus onClick={onKeep}>
          {t('common.discard.keep')}
        </Button>
        <Button color="error" onClick={onDiscard}>
          {t('common.discard.discard')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
