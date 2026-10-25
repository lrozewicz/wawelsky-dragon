// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/hooks/useNotifications/NotificationsContext.tsx (MIT). Zmiany: importy typów przez `import type`, formatowanie Prettier.
import * as React from 'react'
import type { CloseNotification, ShowNotification } from './useNotifications'

const NotificationsContext = React.createContext<{
  show: ShowNotification
  close: CloseNotification
} | null>(null)

export default NotificationsContext
