/**
 * Formularze strony logowania (08 §7.1): logowanie e-mail/hasło i rejestracja, oba na
 * TanStack Form + zod. Komunikaty walidacji to klucze i18n — tłumaczone dopiero przy
 * prezentacji (08 §10.1). Wyodrębnione z `LoginPage.tsx`, żeby zmieścić się w limicie
 * `max-lines` dla `src/features/**`.
 */

import { useState } from 'react'
import type { JSX, ReactNode } from 'react'
import { useForm } from '@tanstack/react-form'
import { useNavigate } from '@tanstack/react-router'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import InputAdornment from '@mui/material/InputAdornment'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { api, apiCall } from '../../api/client'
import { ApiError } from '../../api/envelope'

import type { AuthState } from './authState'

export const loginSchema = z.object({
  email: z.email({ error: 'auth.login.emailInvalid' }),
  password: z.string().min(1, { error: 'auth.login.passwordRequired' }),
})

export const registerSchema = z.object({
  nickname: z.string().min(1, { error: 'auth.login.nicknameRequired' }),
  email: z.email({ error: 'auth.login.emailInvalid' }),
  password: z.string().min(1, { error: 'auth.login.passwordRequired' }),
})

/** To samo sprawdzenie formatu co `z.email` powyżej — wspólne dla logowania, rejestracji
 * i dialogu tworzenia użytkownika (T3: „a@b..c” odrzucone, rozstrzyga backend). */
export function isValidEmail(email: string): boolean {
  return z.email().safeParse(email).success
}

/** Klucz i18n pierwszego błędu pola. StandardSchema (zod) zwraca obiekty `{message}`. */
function errorKeyOf(errors: readonly unknown[]): string | undefined {
  const issue = errors.find(
    (entry): entry is { message: string } =>
      typeof entry === 'object' &&
      entry !== null &&
      'message' in entry &&
      typeof entry.message === 'string',
  )
  return issue?.message
}

type AuthTextFieldProps = {
  testId: string
  label: string
  type: 'text' | 'email' | 'password'
  autoComplete: string
  value: string
  onChange: (value: string) => void
  onBlur: () => void
  errors: readonly unknown[]
  endAdornment?: ReactNode
}

/** Pole tekstowe formularza z walidacją inline; `data-testid` ląduje na samym `<input>`. */
export function AuthTextField(props: AuthTextFieldProps): JSX.Element {
  const { t } = useTranslation()
  const errorKey = errorKeyOf(props.errors)
  const endAdornment = props.endAdornment

  return (
    <TextField
      label={props.label}
      type={props.type}
      autoComplete={props.autoComplete}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      onBlur={props.onBlur}
      error={errorKey !== undefined}
      helperText={errorKey === undefined ? undefined : t(errorKey)}
      fullWidth
      slotProps={{
        htmlInput: { 'data-testid': props.testId },
        input: endAdornment === undefined ? undefined : { endAdornment },
      }}
    />
  )
}

/** Błąd wysyłki: komunikat API (`ApiError`) albo klucz i18n dla nieprzewidzianego błędu. */
export type SubmitError = { kind: 'api'; message: string } | { kind: 'unexpected' }

function AuthErrorAlert(props: { error: SubmitError; testId: string; fallbackKey: string }) {
  const { t } = useTranslation()

  return (
    <Alert severity="error" data-testid={props.testId}>
      {props.error.kind === 'api' ? props.error.message : t(props.fallbackKey)}
    </Alert>
  )
}

/** Błąd z `ApiError` niesie komunikat backendu; każdy inny znaczy „nie udało się” (i18n). */
function submitErrorOf(caught: unknown): SubmitError {
  return caught instanceof ApiError
    ? { kind: 'api', message: caught.message }
    : { kind: 'unexpected' }
}

export function LoginForm(props: { auth: Pick<AuthState, 'login'>; target: string }): JSX.Element {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<SubmitError | null>(null)
  const form = useForm({
    defaultValues: { email: '', password: '' },
    validators: { onSubmit: loginSchema },
    onSubmit: async ({ value }) => {
      setError(null)
      try {
        await props.auth.login(value.email, value.password)
        await navigate({ to: props.target })
      } catch (caught) {
        setError(submitErrorOf(caught))
      }
    },
  })

  return (
    <Stack
      component="form"
      spacing={2}
      onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void form.handleSubmit()
      }}
      noValidate
    >
      {error === null ? null : (
        <AuthErrorAlert error={error} testId="login-error" fallbackKey="auth.login.unexpected" />
      )}
      <form.Field name="email">
        {(field) => (
          <AuthTextField
            testId="login-email"
            label={t('auth.login.email')}
            type="email"
            autoComplete="email"
            value={field.state.value}
            onChange={field.handleChange}
            onBlur={field.handleBlur}
            errors={field.state.meta.errors}
          />
        )}
      </form.Field>
      <form.Field name="password">
        {(field) => (
          <AuthTextField
            testId="login-password"
            label={t('auth.login.password')}
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            value={field.state.value}
            onChange={field.handleChange}
            onBlur={field.handleBlur}
            errors={field.state.meta.errors}
            endAdornment={
              <InputAdornment position="end">
                <IconButton
                  edge="end"
                  aria-label={
                    showPassword ? t('auth.login.hidePassword') : t('auth.login.showPassword')
                  }
                  onClick={() => setShowPassword((previous) => !previous)}
                >
                  {showPassword ? <VisibilityOff /> : <Visibility />}
                </IconButton>
              </InputAdornment>
            }
          />
        )}
      </form.Field>
      <Button type="submit" variant="contained" fullWidth data-testid="login-submit">
        {t('auth.login.submit')}
      </Button>
    </Stack>
  )
}

export function RegisterForm(props: {
  onRegistered: (message: string) => void
  onCancel: () => void
}): JSX.Element {
  const { t } = useTranslation()
  const [error, setError] = useState<SubmitError | null>(null)
  const form = useForm({
    defaultValues: { nickname: '', email: '', password: '' },
    validators: { onSubmit: registerSchema },
    onSubmit: async ({ value }) => {
      setError(null)
      try {
        await apiCall(api.POST('/api/v1/users', { body: value }))
        props.onRegistered(t('auth.register.success'))
      } catch (caught) {
        setError(submitErrorOf(caught))
      }
    },
  })

  return (
    <Stack
      component="form"
      spacing={2}
      onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void form.handleSubmit()
      }}
      noValidate
    >
      {error === null ? null : (
        <AuthErrorAlert
          error={error}
          testId="register-error"
          fallbackKey="auth.login.registerUnexpected"
        />
      )}
      <form.Field name="email">
        {(field) => (
          <AuthTextField
            testId="register-email"
            label={t('auth.login.email')}
            type="email"
            autoComplete="email"
            value={field.state.value}
            onChange={field.handleChange}
            onBlur={field.handleBlur}
            errors={field.state.meta.errors}
          />
        )}
      </form.Field>
      <form.Field name="nickname">
        {(field) => (
          <AuthTextField
            testId="register-nickname"
            label={t('auth.login.nickname')}
            type="text"
            autoComplete="nickname"
            value={field.state.value}
            onChange={field.handleChange}
            onBlur={field.handleBlur}
            errors={field.state.meta.errors}
          />
        )}
      </form.Field>
      <form.Field name="password">
        {(field) => (
          <AuthTextField
            testId="register-password"
            label={t('auth.login.password')}
            type="password"
            autoComplete="new-password"
            value={field.state.value}
            onChange={field.handleChange}
            onBlur={field.handleBlur}
            errors={field.state.meta.errors}
          />
        )}
      </form.Field>
      <Button type="submit" variant="contained" fullWidth data-testid="register-submit">
        {t('auth.login.registerSubmit')}
      </Button>
      <Button variant="text" onClick={props.onCancel}>
        {t('auth.login.loginPrompt')}
      </Button>
    </Stack>
  )
}
