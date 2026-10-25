/**
 * Okno chunku — nowy i edycja (08 §7.5, kontrakt WP E3-4a §ChunkDialog). Wzór formularza:
 * `features/datasets/files/RenameDocumentDialog.tsx` (MUI `Dialog` z `paper` jako `form`, Enter
 * zapisuje). Pola: treść (wymagana po `trim`), typ (tylko edycja, read-only z `doc_type_kwd`),
 * słowa kluczowe i pytania (`Autocomplete multiple freeSolo` — Enter dodaje `Chip`), włączony.
 * Walidacja idzie przez `chunkFormSchema`, więc `onSubmit` dostaje treść przyciętą.
 * Stan pól startuje z `chunk` i jest zerowany przez `key` przy każdym otwarciu lub zmianie chunku.
 */

import * as React from 'react'
import { useState } from 'react'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import { chunkFormSchema } from './chunkSchema'
import type { Chunk } from './queries'

export type ChunkDialogProps = {
  open: boolean
  /** `null` = tryb „Nowy chunk”; wtedy pola startują puste, a typ nie jest pokazywany. */
  chunk: Chunk | null
  saving: boolean
  onClose: () => void
  onSubmit: (values: {
    content: string
    important_keywords: string[]
    questions: string[]
    available: boolean
  }) => void
}

/** Klucz etykiety typu chunku z `doc_type_kwd`; nieznana wartość (m.in. `''`) znaczy „tekst”. */
function chunkTypeKey(chunk: Chunk | null): string {
  const type = chunk?.doc_type_kwd ?? ''
  return type === 'table' || type === 'image' ? type : 'text'
}

type TagsFieldProps = {
  testId: string
  label: string
  helperText?: string
  value: string[]
  onChange: (value: string[]) => void
}

/** Lista tekstów: `Autocomplete multiple freeSolo` bez opcji — Enter zamienia wpisany tekst w `Chip`
 * (domyślny `renderValue` MUI rysuje wartości jako `Chip`; `options=[]`, więc nie ma podpowiedzi). */
function TagsField(props: TagsFieldProps) {
  return (
    <Autocomplete
      multiple
      freeSolo
      options={[]}
      data-testid={props.testId}
      value={props.value}
      onChange={(_event, next) => props.onChange(next)}
      renderInput={(params) => (
        <TextField {...params} margin="dense" label={props.label} helperText={props.helperText} />
      )}
    />
  )
}

function ChunkDialogForm(props: ChunkDialogProps) {
  const { open, chunk, saving, onClose, onSubmit } = props
  const { t } = useTranslation()
  const [content, setContent] = useState(chunk?.content ?? '')
  const [keywords, setKeywords] = useState<string[]>(chunk?.important_keywords ?? [])
  const [questions, setQuestions] = useState<string[]>(chunk?.questions ?? [])
  const [available, setAvailable] = useState(chunk?.available ?? true)
  const [contentError, setContentError] = useState(false)

  function submit(): void {
    const parsed = chunkFormSchema.safeParse({
      content,
      important_keywords: keywords,
      questions,
      available,
    })
    if (!parsed.success) {
      setContentError(true)
      return
    }
    onSubmit(parsed.data)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="md"
      data-testid="chunk-dialog"
      slotProps={{
        // MUI typuje slot `paper` po `Paper` (propsy `div`), więc prop formularza (`noValidate`)
        // jest poza tym typem i slot trzeba zawęzić rzutowaniem do propsów `form`.
        paper: {
          component: 'form',
          // Natywna walidacja przeglądarki blokowałaby `submit` przy pustym polu `required`
          // i komunikat z `chunkFormSchema` nigdy by się nie pokazał (D2 po QA-UI).
          noValidate: true,
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            submit()
          },
        } as React.ComponentPropsWithRef<'form'>,
      }}
    >
      <DialogTitle>
        {chunk === null ? t('chunks.dialog.titleNew') : t('chunks.dialog.titleEdit')}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            autoFocus
            required
            fullWidth
            multiline
            minRows={6}
            margin="dense"
            label={t('chunks.dialog.content')}
            value={content}
            error={contentError}
            helperText={contentError ? t('chunks.dialog.contentRequired') : undefined}
            onChange={(event) => {
              setContent(event.target.value)
              setContentError(false)
            }}
            slotProps={{ htmlInput: { 'data-testid': 'chunk-dialog-content' } }}
          />
          {chunk === null ? null : (
            <TextField
              disabled
              fullWidth
              margin="dense"
              label={t('chunks.dialog.type')}
              value={t(`chunks.type.${chunkTypeKey(chunk)}`)}
            />
          )}
          <TagsField
            testId="chunk-dialog-keywords"
            label={t('chunks.dialog.keywords')}
            value={keywords}
            onChange={setKeywords}
          />
          <TagsField
            testId="chunk-dialog-questions"
            label={t('chunks.dialog.questions')}
            helperText={t('chunks.dialog.questionsHint')}
            value={questions}
            onChange={setQuestions}
          />
          <FormControlLabel
            control={
              <Switch
                checked={available}
                data-testid="chunk-dialog-available"
                onChange={(event) => setAvailable(event.target.checked)}
              />
            }
            label={t('chunks.dialog.available')}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('chunks.dialog.cancel')}</Button>
        <Button
          data-testid="chunk-dialog-save"
          type="submit"
          variant="contained"
          loading={saving}
          disabled={saving}
        >
          {t('chunks.dialog.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export function ChunkDialog(props: ChunkDialogProps) {
  // `key` remountuje formularz przy każdym otwarciu i przy zmianie `chunk` — pola wracają do
  // wartości początkowych bez efektu ze `setState` (kontrakt §ChunkDialog pkt 3).
  const formKey = `${props.chunk?.id ?? 'new'}:${props.open ? 'open' : 'closed'}`
  return <ChunkDialogForm key={formKey} {...props} />
}
