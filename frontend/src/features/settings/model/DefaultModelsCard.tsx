/**
 * Karta „Modele domyślne” (brief E3-6c1 T5a): selecty LLM i Embedding (wymagane), Rerank oraz
 * VLM w sekcji zaawansowanej. Zapis idzie przez `PATCH /api/v1/users/me/models` wyłącznie dla
 * superusera; pozostali widzą odczyt (kontrakt WP E3-6c1 §0).
 */

import { useState } from 'react'
import type { ChangeEvent, JSX } from 'react'
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import MenuItem from '@mui/material/MenuItem'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { modelsQueryOptions } from '../../models/queries'
import type { DefaultModels } from '../../models/queries'
import { registryQueryOptions, useUpdateDefaultModels } from '../queries'
import type { RegistryModel } from '../queries'
import { useIsSuperuser } from '../useIsSuperuser'

import { buildDefaultsPatch, toDefaultsForm } from './defaultModels'
import type { DefaultsForm } from './defaultModels'

/** Wysokość szkieletu karty — jak karta z czterema polami. */
const CARD_SKELETON_HEIGHT = 220

/**
 * Typy modelu z rejestru pasujące do danego selecta (kontrakt §0, brief pkt 1).
 * VLM akceptuje oba oznaczenia modelu wizji: `vision` i backendowe `image2text`.
 */
const TYPES_BY_FIELD: Record<keyof DefaultsForm, readonly string[]> = {
  llm: ['chat'],
  embd: ['embedding'],
  rerank: ['rerank'],
  vlm: ['vision', 'image2text'],
}

/** Opcje selecta: modele rejestru, których `model_type` zawiera choć jeden typ pola. */
function optionsFor(registry: RegistryModel[], field: keyof DefaultsForm): RegistryModel[] {
  const types = TYPES_BY_FIELD[field]
  return registry.filter((model) => model.model_type.some((type) => types.includes(type)))
}

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export function DefaultModelsCard(): JSX.Element {
  const { t } = useTranslation()
  const isSuperuser = useIsSuperuser()
  const models = useQuery(modelsQueryOptions())
  const registry = useQuery(registryQueryOptions())

  if (models.isError || registry.isError) {
    return (
      <Alert severity="error">
        {errorText(
          models.error ?? registry.error,
          t('settings.error.title'),
          t('settings.defaults.error'),
        )}
      </Alert>
    )
  }
  if (models.data === undefined || registry.data === undefined) {
    return (
      <Skeleton data-testid="defaults-loading" variant="rounded" height={CARD_SKELETON_HEIGHT} />
    )
  }

  return <DefaultsFields initial={models.data} registry={registry.data} isSuperuser={isSuperuser} />
}

type DefaultsFieldsProps = {
  initial: DefaultModels
  registry: RegistryModel[]
  isSuperuser: boolean
}

function DefaultsFields(props: DefaultsFieldsProps): JSX.Element {
  const { initial, registry, isSuperuser } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const update = useUpdateDefaultModels()
  const [form, setForm] = useState<DefaultsForm>(() => toDefaultsForm(initial))

  const patch = buildDefaultsPatch(toDefaultsForm(initial), form)
  const changed = Object.keys(patch).length > 0

  const change = (field: keyof DefaultsForm) => (event: ChangeEvent<HTMLInputElement>) => {
    setForm((current) => ({ ...current, [field]: event.target.value }))
  }

  function save(): void {
    // Część pól zostaje pominięta świadomie (tylko zmienione i niepuste) — kontrakt §0.
    // Pola `UpdateDefaultModelsRequest` są opcjonalne (po E2-H2), więc typ `Partial` pasuje bez rzutowania.
    update.mutate(patch, {
      onSuccess: () => show(t('settings.defaults.saved'), { severity: 'success' }),
    })
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            {t('settings.defaults.title')}
          </Typography>

          {!isSuperuser ? <Alert severity="info">{t('settings.readOnly')}</Alert> : null}

          <TextField
            select
            size="small"
            required
            label={t('settings.defaults.llm')}
            value={form.llm}
            disabled={!isSuperuser}
            onChange={change('llm')}
            data-testid="defaults-llm"
          >
            {optionsFor(registry, 'llm').map((model) => (
              <MenuItem key={model.model_id} value={model.name}>
                {model.name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            required
            label={t('settings.defaults.embedding')}
            value={form.embd}
            disabled={!isSuperuser}
            onChange={change('embd')}
            data-testid="defaults-embedding"
          >
            {optionsFor(registry, 'embd').map((model) => (
              <MenuItem key={model.model_id} value={model.name}>
                {model.name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label={t('settings.defaults.rerank')}
            value={form.rerank}
            disabled={!isSuperuser}
            onChange={change('rerank')}
            // Pusty wybór ma pokazywać „Brak”, nie puste pole (opcja `value=""`); etykieta
            // zawsze uniesiona — inaczej MUI trzyma ją w polu i nachodzi na „Brak”
            // (QA E5-H8z-2 C2, E5-H8z-3 D2). Ten sam wzorzec co `SettingsCard`/`ApiKeysDialog`.
            slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
            data-testid="defaults-rerank"
          >
            <MenuItem value="">{t('settings.defaults.none')}</MenuItem>
            {optionsFor(registry, 'rerank').map((model) => (
              <MenuItem key={model.model_id} value={model.name}>
                {model.name}
              </MenuItem>
            ))}
          </TextField>

          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
              {t('settings.defaults.advanced')}
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1}>
                <Typography variant="body2" color="text.secondary">
                  {t('settings.defaults.vlmHint')}
                </Typography>
                <TextField
                  select
                  size="small"
                  label={t('settings.defaults.vlm')}
                  value={form.vlm}
                  disabled={!isSuperuser}
                  onChange={change('vlm')}
                  // Jak w reranku: „Brak” + uniesiona etykieta (ta sama przyczyna, QA E5-H8z-3 D2).
                  slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
                  data-testid="defaults-vlm"
                >
                  <MenuItem value="">{t('settings.defaults.none')}</MenuItem>
                  {optionsFor(registry, 'vlm').map((model) => (
                    <MenuItem key={model.model_id} value={model.name}>
                      {model.name}
                    </MenuItem>
                  ))}
                </TextField>
              </Stack>
            </AccordionDetails>
          </Accordion>

          {isSuperuser ? (
            <Button
              variant="contained"
              disabled={!changed || update.isPending}
              onClick={save}
              sx={{ alignSelf: 'flex-start' }}
            >
              {t('settings.common.save')}
            </Button>
          ) : null}

          {update.isError ? (
            <Alert severity="error">
              {errorText(update.error, t('settings.error.title'), t('settings.defaults.error'))}
            </Alert>
          ) : null}
        </Stack>
      </CardContent>
    </Card>
  )
}
