/**
 * Wspólne okno potwierdzenia akcji nieodwracalnej (08 §7.3): tytuł, komunikat i para przycisków.
 * Sygnatura z kontraktu WP E3-5a §5 (nie mylić z `ConfirmDialog` z `hooks/useDialogs`, który jest
 * komponentem wewnętrznym hooka `confirm`).
 */

import type { ReactNode } from 'react'

import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'

export type ConfirmDialogProps = {
  open: boolean
  title: string
  message: string
  confirmLabel: string
  cancelLabel: string
  loading?: boolean
  /** Dodatkowe opcje akcji (np. checkbox pełnej synchronizacji) tuż pod komunikatem. */
  children?: ReactNode
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  const {
    open,
    title,
    message,
    confirmLabel,
    cancelLabel,
    loading,
    children,
    onConfirm,
    onCancel,
  } = props

  return (
    <Dialog open={open} onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {/* Długa nazwa w komunikacie (np. „Usuń czat …”, SC-V13-12): zawijanie także bez
            spacji w treści (U2 — wielowierszowy tekst się zawija, nigdy ucięcie). */}
        <DialogContentText sx={{ overflowWrap: 'anywhere' }}>{message}</DialogContentText>
        {children}
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>{cancelLabel}</Button>
        <Button color="error" loading={loading} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
