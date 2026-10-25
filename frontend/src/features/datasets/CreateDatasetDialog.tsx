/**
 * Dialog „Utwórz dataset” (08 §7.3, kontrakt WP E3-3a §T2): nazwa, model embeddingu i metoda
 * chunkowania. Model embeddingu podpowiada domyślny model instancji (`GET /users/me/models`),
 * a listę dają modele embeddingu z `GET /models` (mapowanie `name` → `model_id` w
 * `buildEmbeddingOptions`, bo `POST /datasets` chce `model_id`). Walidacja U11 (kontrakt K2):
 * przycisk zapisu pozostaje aktywny; pod pustą nazwą po dotknięciu pola albo próbie wysłania
 * pojawia się `datasets.create.nameRequired` (kontrakt WP E3-3b §T4), a klik bez nazwy albo bez
 * modelu embeddingu wraca fokusem do pierwszego błędnego pola z `common.required` pod nim.
 * Błąd API wraca tu jako `Alert`, a sukces oddajemy wołającemu (nawigację robi strona listy).
 */

import * as React from 'react'
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import { modelsListQueryOptions } from '../chats/modelsQuery'
import { modelsQueryOptions } from '../models/queries'

import { mutationMessage } from './config/helpers'
import { buildEmbeddingOptions } from './embeddingOptions'
import { CHUNK_METHODS, useCreateDataset } from './queries'
import type { ChunkMethod } from './queries'

export type CreateDatasetDialogProps = {
  onCreated: (id: string) => void
  onClose: () => void
}

export function CreateDatasetDialog(props: CreateDatasetDialogProps) {
  const { t } = useTranslation()
  const createDataset = useCreateDataset()
  const models = useQuery(modelsListQueryOptions())
  const defaultModels = useQuery(modelsQueryOptions())

  const [name, setName] = useState('')
  // Komunikat „nazwa wymagana” dopiero po dotknięciu pola albo próbie wysłania (kontrakt §T4).
  const [nameTouched, setNameTouched] = useState(false)
  // Brak modelu embeddingu (instancja bez modeli) sygnalizujemy po próbie wysłania.
  const [embeddingTouched, setEmbeddingTouched] = useState(false)
  // `null` = jeszcze nie wybrano ręcznie → obowiązuje model domyślny z `/users/me/models`.
  const [embeddingId, setEmbeddingId] = useState<string | null>(null)
  const [chunkMethod, setChunkMethod] = useState<ChunkMethod>('naive')
  const nameRef = useRef<HTMLInputElement>(null)
  const embeddingRef = useRef<HTMLInputElement>(null)

  const { options, defaultId } = buildEmbeddingOptions(
    models.data ?? [],
    defaultModels.data?.embd_id ?? '',
  )
  const selectedId = embeddingId ?? defaultId
  const selectedOption = options.find((option) => option.id === selectedId) ?? null

  const trimmed = name.trim()
  const showNameError = nameTouched && trimmed === ''
  const showEmbeddingError = embeddingTouched && selectedId === ''

  function submit(): void {
    setNameTouched(true)
    if (trimmed === '') {
      // U11: fokus na pierwszym błędnym polu (nazwa jest pierwsza w formularzu).
      nameRef.current?.focus()
      return
    }
    if (selectedId === '') {
      setEmbeddingTouched(true)
      embeddingRef.current?.focus()
      return
    }
    createDataset.mutate(
      { name: trimmed, embeddingModel: selectedId, chunkMethod },
      { onSuccess: (dataset) => props.onCreated(dataset.id) },
    )
  }

  return (
    <Dialog
      open
      onClose={props.onClose}
      maxWidth="sm"
      fullWidth
      slotProps={{
        paper: {
          component: 'form',
          // Natywna walidacja przeglądarki blokowałaby `submit` przy pustym polu `required`
          // (wzór: `ChunkDialog`).
          noValidate: true,
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            submit()
          },
        } as React.ComponentPropsWithRef<'form'>,
      }}
    >
      <DialogTitle>{t('datasets.create.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {createDataset.error !== null ? (
            <Alert severity="error">
              {mutationMessage(createDataset.error, t('datasets.create.error'), t)}
            </Alert>
          ) : null}
          <TextField
            autoFocus
            required
            fullWidth
            margin="dense"
            label={t('datasets.create.name')}
            value={name}
            inputRef={nameRef}
            error={showNameError}
            helperText={showNameError ? t('datasets.create.nameRequired') : undefined}
            slotProps={{ inputLabel: { shrink: showNameError ? true : undefined } }}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => setNameTouched(true)}
          />
          <Autocomplete
            options={options}
            value={selectedOption}
            disableClearable={options.length > 0}
            getOptionLabel={(option) => option.label}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            onChange={(_event, next) => {
              setEmbeddingId(next?.id ?? null)
              setEmbeddingTouched(false)
            }}
            renderInput={(params) => (
              <TextField
                {...params}
                required
                margin="dense"
                label={t('datasets.create.embedding')}
                inputRef={embeddingRef}
                error={showEmbeddingError}
                helperText={showEmbeddingError ? t('common.required') : undefined}
                // `params.slotProps` niosą `role="combobox"` i refy Autocomplete — nadpisując
                // sloty, trzeba je scalić, inaczej pole traci semantykę combobox.
                slotProps={{
                  ...params.slotProps,
                  inputLabel: {
                    ...params.slotProps.inputLabel,
                    shrink: showEmbeddingError ? true : undefined,
                  },
                }}
              />
            )}
          />
          <TextField
            select
            required
            fullWidth
            margin="dense"
            label={t('datasets.create.chunkMethod')}
            value={chunkMethod}
            helperText={t(`datasets.method.${chunkMethod}.desc`)}
            slotProps={{
              select: {
                onChange: (event) => setChunkMethod(event.target.value as ChunkMethod),
              },
            }}
          >
            {CHUNK_METHODS.map((method) => (
              <MenuItem key={method} value={method}>
                {t(`datasets.method.${method}`)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={props.onClose}>{t('common.cancel')}</Button>
        <Button type="submit" variant="contained" loading={createDataset.isPending}>
          {t('datasets.create.submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
