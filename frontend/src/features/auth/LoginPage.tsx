/**
 * Strona logowania (08 §7.1, wzorzec szablonu MUI `sign-in`): gradient w tle, przełącznik trybu
 * kolorów w prawym górnym rogu, `Card` z logo, formularz e-mail/hasło, `Divider` „lub” z kanałami
 * OIDC i — gdy instancja pozwala — przełącznik rejestracji. Formularze: `authForm.tsx`.
 * Pole „zapamiętaj mnie” i „Zapomniałeś hasła?” są pominięte: backend ich nie wspiera (CONTRACT).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { styled } from '@mui/material/styles'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { BrandLogo } from '../../theme/BrandLogo'
import ColorModeSelect from '../../theme/ColorModeSelect'

import { LoginForm, RegisterForm } from './authForm'
import type { AuthState } from './authState'
import type { LoginChannel } from './queries'
import { useLoginChannels, useSystemConfig } from './queries'
import { safeRedirect } from './redirect'

const SignInContainer = styled(Stack)(({ theme }) => ({
  minHeight: '100dvh',
  padding: theme.spacing(2),
  [theme.breakpoints.up('sm')]: { padding: theme.spacing(4) },
  '&::before': {
    content: '""',
    display: 'block',
    position: 'absolute',
    zIndex: -1,
    inset: 0,
    backgroundImage: 'radial-gradient(ellipse at 50% 50%, hsl(210, 100%, 97%), hsl(0, 0%, 100%))',
    backgroundRepeat: 'no-repeat',
    ...theme.applyStyles('dark', {
      backgroundImage: 'radial-gradient(at 50% 50%, hsla(210, 100%, 16%, 0.5), hsl(220, 30%, 5%))',
    }),
  },
}))

/** Kanały OIDC: pełna nawigacja przeglądarki (`href`), więc `<Button component="a">`, nie router. */
function ChannelButtons(props: { channels: LoginChannel[]; target: string; withDivider: boolean }) {
  const { t } = useTranslation()

  if (props.channels.length === 0) return null

  return (
    <>
      {props.withDivider ? <Divider>{t('auth.channels.divider')}</Divider> : null}
      <Stack spacing={1}>
        {props.channels.map((channel) => (
          <Button
            key={channel.channel}
            component="a"
            variant="outlined"
            fullWidth
            data-testid={`login-channel-${channel.channel}`}
            href={`/api/v1/auth/login/keycloak?redirect=${encodeURIComponent(props.target)}`}
          >
            {channel.display_name}
          </Button>
        ))}
      </Stack>
    </>
  )
}

export type LoginPageProps = {
  /** Sesja z kontekstu trasy (`Route.useRouteContext().auth`) — używamy tylko `login`. */
  auth: Pick<AuthState, 'login'>
  /** Parametr `?redirect=`; przepuszczony przez `safeRedirect`. */
  redirectTo?: string
}

export function LoginPage({ auth, redirectTo }: LoginPageProps): JSX.Element {
  const { t } = useTranslation()
  const channels = useLoginChannels()
  const config = useSystemConfig()
  const [registering, setRegistering] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const target = safeRedirect(redirectTo)
  // Brak odpowiedzi `system/config` → logowanie hasłem traktujemy jak włączone (brak flagi ≠ zakaz).
  const passwordEnabled = config?.disablePasswordLogin !== true

  function handleRegistered(message: string): void {
    setNotice(message)
    setRegistering(false)
  }

  return (
    <SignInContainer direction="column" sx={{ justifyContent: 'center', alignItems: 'center' }}>
      <Stack
        direction="row"
        spacing={1}
        sx={{ position: 'fixed', top: '1rem', right: '1rem', alignItems: 'center' }}
      >
        <Typography id="login-theme-label" variant="body2" color="text.secondary">
          {t('auth.login.theme')}
        </Typography>
        <ColorModeSelect size="small" aria-label={undefined} labelId="login-theme-label" />
      </Stack>
      <Card variant="outlined" sx={{ width: '100%', maxWidth: 420 }}>
        <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', alignSelf: 'center' }}>
            <BrandLogo size={28} />
            <Typography variant="h6">{t('app.name')}</Typography>
          </Stack>
          <Typography component="h1" variant="h5">
            {registering ? t('auth.login.registerTitle') : t('auth.login.title')}
          </Typography>
          {notice === null ? null : <Alert severity="success">{notice}</Alert>}
          {registering ? (
            <RegisterForm onRegistered={handleRegistered} onCancel={() => setRegistering(false)} />
          ) : (
            <>
              {passwordEnabled ? <LoginForm auth={auth} target={target} /> : null}
              <ChannelButtons channels={channels} target={target} withDivider={passwordEnabled} />
              {config?.registerEnabled === 1 ? (
                <Button
                  variant="text"
                  onClick={() => {
                    setNotice(null)
                    setRegistering(true)
                  }}
                >
                  {t('auth.login.registerPrompt')}
                </Button>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </SignInContainer>
  )
}
