/**
 * Dialog formularza integracji SharePoint (kontrakt WP E4-3c §1, brief T3): tworzenie i edycja,
 * walidacja pól, test połączenia przed i po zapisie oraz sekret wyłącznie do wpisania.
 * Treść dialogu istnieje tylko przy `open` i jest kluczowana po integracji — zamknięcie (albo
 * zmiana edytowanego rekordu) odmontowuje stan, więc sekret nie zostaje w formularzu,
 * a kolejne otwarcie startuje z `DEFAULT_FORM_VALUES`/`formValuesFromIntegration`.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { useFullScreenDialog } from '../../../components/useFullScreenDialog'
import { WdApiError, wdErrorKey } from '../wdClient'

import { ConnectionTestResult } from './ConnectionTestResult'
import { IntegrationFormFields } from './IntegrationFormFields'
import {
  useCreateIntegration,
  useTestConnection,
  useTestSavedConnection,
  useUpdateIntegration,
} from './queries'
import type { ConnectionTest, Integration } from './queries'
import {
  DEFAULT_FORM_VALUES,
  formValuesFromIntegration,
  toCreateBody,
  toSavedTestBody,
  toTestBody,
  toUpdateBody,
  validateForm,
} from './schema'
import type { IntegrationFormValues } from './schema'

export type IntegrationFormDialogProps = {
  open: boolean
  integration: Integration | null
  onClose: () => void
}

/** Zajęty dataset ma w formularzu własny komunikat (kontrakt §0/§2: 409 `conflict`). */
function dialogErrorKey(err: unknown): string {
  if (err instanceof WdApiError && err.code === 'conflict') {
    return 'integrations.form.error.conflict'
  }
  return wdErrorKey(err)
}

export function IntegrationFormDialog(props: IntegrationFormDialogProps): JSX.Element {
  const { open, integration, onClose } = props
  const { t } = useTranslation()
  const mode = integration === null ? 'create' : 'edit'
  // Poniżej `sm` (m.in. 390 px) dialog zajmuje cały ekran, jak pozostałe widoki mobilne.
  const belowSm = useFullScreenDialog()

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      fullScreen={belowSm}
      data-testid="integration-form"
    >
      <DialogTitle>{t(`integrations.form.title.${mode}`)}</DialogTitle>
      {open ? (
        <IntegrationFormBody
          key={integration?.id ?? 'create'}
          mode={mode}
          integration={integration}
          onClose={onClose}
        />
      ) : null}
    </Dialog>
  )
}

type IntegrationFormBodyProps = {
  mode: 'create' | 'edit'
  integration: Integration | null
  onClose: () => void
}

function IntegrationFormBody(props: IntegrationFormBodyProps): JSX.Element {
  const { mode, integration, onClose } = props
  const { t } = useTranslation()
  // Id dla mutacji zapisanej integracji; w trybie tworzenia hooki dostają 0 i nie są wołane.
  const id = integration?.id ?? 0
  const create = useCreateIntegration()
  const update = useUpdateIntegration(id)
  const testNew = useTestConnection()
  const testSaved = useTestSavedConnection(id)
  const [values, setValues] = useState<IntegrationFormValues>(() =>
    integration === null ? DEFAULT_FORM_VALUES : formValuesFromIntegration(integration),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [testResult, setTestResult] = useState<ConnectionTest | null>(null)

  const saving = create.isPending || update.isPending
  const testing = testNew.isPending || testSaved.isPending
  const saveError = create.error ?? update.error
  const testError = testNew.error ?? testSaved.error

  /** Anulowanie i sukces zapisu: czyścimy mutacje i oddajemy sterowanie rodzicowi. */
  function close(): void {
    create.reset()
    update.reset()
    testNew.reset()
    testSaved.reset()
    onClose()
  }

  /** Wspólny krok zapisu i testu: walidacja pól; `{}` znaczy „można działać”. */
  function validate(): Record<string, string> {
    const found = validateForm(values, mode)
    setErrors(found)
    return found
  }

  function save(): void {
    if (Object.keys(validate()).length > 0) return
    if (mode === 'create') {
      create.mutate(toCreateBody(values), { onSuccess: close })
    } else {
      update.mutate(toUpdateBody(values), { onSuccess: close })
    }
  }

  /** Test przed zapisem (tryb tworzenia) albo istniejącej integracji z nadpisaniami (edycja). */
  function runTest(): void {
    if (Object.keys(validate()).length > 0) return
    testNew.reset()
    testSaved.reset()
    setTestResult(null)
    if (mode === 'create') {
      testNew.mutate(toTestBody(values), { onSuccess: setTestResult })
    } else {
      testSaved.mutate(toSavedTestBody(values), { onSuccess: setTestResult })
    }
  }

  return (
    <>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {saveError === null ? null : (
            <Alert severity="error">
              {saveError instanceof WdApiError &&
              saveError.httpStatus === 400 &&
              saveError.message !== ''
                ? saveError.message
                : t(dialogErrorKey(saveError))}
            </Alert>
          )}
          {testError === null ? null : (
            <Alert severity="error">{t(dialogErrorKey(testError))}</Alert>
          )}

          <IntegrationFormFields
            mode={mode}
            values={values}
            errors={errors}
            maskedSecret={integration?.client_secret_masked ?? null}
            onChange={(patch) => setValues((current) => ({ ...current, ...patch }))}
          />

          {testResult === null ? null : <ConnectionTestResult result={testResult} />}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('integrations.form.cancel')}</Button>
        <Button data-testid="integration-test" disabled={testing || saving} onClick={runTest}>
          {testing ? t('integrations.test.running') : t('integrations.test.run')}
        </Button>
        <Button data-testid="integration-save" variant="contained" disabled={saving} onClick={save}>
          {t('integrations.form.save')}
        </Button>
      </DialogActions>
    </>
  )
}
