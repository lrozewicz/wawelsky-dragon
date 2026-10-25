/**
 * Okno uzasadnienia negatywnego feedbacku (kontrakt WP E3-5b §T5b): wielolinijkowe pole tekstowe,
 * „Wyślij” zgłasza uzasadnienie, puste (po trim) idzie jako `null`.
 * Wołający renderuje komponent tylko wtedy, gdy okno ma być widoczne.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

export type FeedbackDialogProps = {
  /** Uzasadnienie (`null`, gdy pole puste) — wołający mapuje je na `onFeedback`. */
  onSubmit: (feedback: string | null) => void
  onClose: () => void
}

export function FeedbackDialog(props: FeedbackDialogProps): JSX.Element {
  const { onSubmit, onClose } = props
  const { t } = useTranslation()
  const [text, setText] = useState('')

  function submit(): void {
    const feedback = text.trim()
    onSubmit(feedback === '' ? null : feedback)
  }

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('chat.msg.feedbackTitle')}</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          multiline
          minRows={3}
          margin="dense"
          label={t('chat.msg.feedbackLabel')}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="contained" onClick={submit}>
          {t('chat.msg.feedbackSend')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
