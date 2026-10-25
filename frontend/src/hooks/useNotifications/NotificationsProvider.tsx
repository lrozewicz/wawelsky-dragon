// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/hooks/useNotifications/NotificationsProvider.tsx (MIT). Zmiany: etykiety domyślne z i18n przez `useTranslation` (CONTRACT C6), importy typów przez `import type`, nieużywany parametr `event` → `_event` (`noUnusedParameters`), formatowanie Prettier. Dodatkowo (kontrakt WP E3-7 §C3): domyślny `autoHideDuration` zależny od `severity`, limit `NOTIFICATION_MAX_VISIBLE` wpisów w kolejce oraz deduplikacja po treści (`message`/`severity`); `useRef` lustra kolejki, by klucz duplikatu był znany synchronicznie.
import * as React from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Badge from '@mui/material/Badge'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import Snackbar from '@mui/material/Snackbar'
import SnackbarContent from '@mui/material/SnackbarContent'
import type { SnackbarCloseReason } from '@mui/material/Snackbar'
import type { CloseReason } from '@mui/material/SpeedDial'
import CloseIcon from '@mui/icons-material/Close'
import useSlotProps from '@mui/utils/useSlotProps'
import NotificationsContext from './NotificationsContext'
import type {
  CloseNotification,
  ShowNotification,
  ShowNotificationOptions,
} from './useNotifications'

const RootPropsContext = React.createContext<NotificationsProviderProps | null>(null)

interface NotificationProps {
  notificationKey: string
  badge: string | null
  open: boolean
  message: React.ReactNode
  options: ShowNotificationOptions
}

function Notification({ notificationKey, open, message, options, badge }: NotificationProps) {
  const { t } = useTranslation()
  const notificationsContext = React.useContext(NotificationsContext)
  if (!notificationsContext) {
    throw new Error('Notifications context was used without a provider.')
  }
  const { close } = notificationsContext

  const { severity, actionText, onAction, autoHideDuration } = options

  const handleClose = React.useCallback(
    (_event: unknown, reason?: CloseReason | SnackbarCloseReason) => {
      if (reason === 'clickaway') {
        return
      }
      close(notificationKey)
    },
    [notificationKey, close],
  )

  const action = (
    <React.Fragment>
      {onAction ? (
        <Button color="inherit" size="small" onClick={onAction}>
          {actionText ?? t('common.action')}
        </Button>
      ) : null}
      <IconButton
        size="small"
        aria-label={t('common.close')}
        title={t('common.close')}
        color="inherit"
        onClick={handleClose}
      >
        <CloseIcon fontSize="small" />
      </IconButton>
    </React.Fragment>
  )

  const props = React.useContext(RootPropsContext)
  // Od md prawy dolny róg (sidebar jest po lewej), niżej dolny środek z marginesem 16 px.
  const theme = useTheme()
  const desktop = useMediaQuery(theme.breakpoints.up('md'))
  const snackbarSlotProps = useSlotProps({
    elementType: Snackbar,
    ownerState: props,
    externalSlotProps: {},
    additionalProps: {
      open,
      autoHideDuration,
      onClose: handleClose,
      action,
      anchorOrigin: {
        vertical: 'bottom' as const,
        horizontal: desktop ? ('right' as const) : ('center' as const),
      },
      sx: { bottom: { xs: 16, md: 24 }, left: { xs: 16, md: 'auto' }, right: { xs: 16, md: 24 } },
    },
  })

  return (
    <Snackbar key={notificationKey} {...snackbarSlotProps}>
      <Badge badgeContent={badge} color="primary" sx={{ width: '100%' }}>
        {severity ? (
          <Alert severity={severity} sx={{ width: '100%' }} action={action}>
            {message}
          </Alert>
        ) : (
          <SnackbarContent message={message} action={action} />
        )}
      </Badge>
    </Snackbar>
  )
}

interface NotificationQueueEntry {
  notificationKey: string
  options: ShowNotificationOptions
  open: boolean
  message: React.ReactNode
}

interface NotificationsState {
  queue: NotificationQueueEntry[]
}

/** Maksymalna liczba powiadomień trzymanych w kolejce (kontrakt WP E3-7 §C3). */
export const NOTIFICATION_MAX_VISIBLE = 3

/** Domyślny czas auto-zamknięcia zależny od wagi powiadomienia (kontrakt WP E3-7 §C3). */
function defaultAutoHideDuration(
  severity: ShowNotificationOptions['severity'],
): number | undefined {
  if (severity === 'error') {
    return undefined
  }
  return severity === 'warning' ? 8000 : 5000
}

interface NotificationsProps {
  state: NotificationsState
}

function Notifications({ state }: NotificationsProps) {
  const currentNotification = state.queue[0] ?? null

  return currentNotification ? (
    <Notification
      {...currentNotification}
      badge={state.queue.length > 1 ? String(state.queue.length) : null}
    />
  ) : null
}

export interface NotificationsProviderProps {
  children?: React.ReactNode
}

let nextId = 0
const generateId = () => {
  const id = nextId
  nextId += 1
  return id
}

/**
 * Provider for Notifications. The subtree of this component can use the `useNotifications` hook to
 * access the notifications API. The notifications are shown in the same order they are requested.
 */
export default function NotificationsProvider(props: NotificationsProviderProps) {
  const { children } = props
  const [state, setState] = React.useState<NotificationsState>({ queue: [] })
  // Lustro kolejki: `show` zwraca klucz duplikatu synchronicznie, więc stan (asynchroniczny)
  // nie wystarczy — ref trzymamy w kroku z każdą zmianą (kontrakt WP E3-7 §C3).
  const queueRef = React.useRef<NotificationQueueEntry[]>([])

  const show = React.useCallback<ShowNotification>((message, options = {}) => {
    const queue = queueRef.current
    // Duplikat treści: ten sam string i ta sama waga → zwracamy klucz istniejącego, nic nie dodajemy.
    if (typeof message === 'string') {
      const duplicate = queue.find(
        (entry) => entry.message === message && entry.options.severity === options.severity,
      )
      if (duplicate) {
        return duplicate.notificationKey
      }
    }
    const notificationKey = options.key ?? `::toolpad-internal::notification::${generateId()}`
    if (queue.some((entry) => entry.notificationKey === notificationKey)) {
      // deduplicate by key
      return notificationKey
    }
    const entry: NotificationQueueEntry = {
      message,
      options: {
        ...options,
        autoHideDuration: options.autoHideDuration ?? defaultAutoHideDuration(options.severity),
      },
      notificationKey,
      open: true,
    }
    // Limit widocznych: przy przepełnieniu najstarsze powiadomienie wypada z kolejki.
    const nextQueue = [...queue, entry].slice(-NOTIFICATION_MAX_VISIBLE)
    queueRef.current = nextQueue
    setState({ queue: nextQueue })
    return notificationKey
  }, [])

  const close = React.useCallback<CloseNotification>((key) => {
    const nextQueue = queueRef.current.filter((entry) => entry.notificationKey !== key)
    queueRef.current = nextQueue
    setState({ queue: nextQueue })
  }, [])

  const contextValue = React.useMemo(() => ({ show, close }), [show, close])

  return (
    <RootPropsContext.Provider value={props}>
      <NotificationsContext.Provider value={contextValue}>
        {children}
        <Notifications state={state} />
      </NotificationsContext.Provider>
    </RootPropsContext.Provider>
  )
}
