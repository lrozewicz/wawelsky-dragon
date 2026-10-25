import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'

import { queryClient } from './app/queryClient'
import { router } from './app/router'
import DialogsProvider from './hooks/useDialogs/DialogsProvider'
import NotificationsProvider from './hooks/useNotifications/NotificationsProvider'
import { initI18n } from './i18n'
import AppTheme from './theme/AppTheme'

// Język musi być gotowy przed pierwszym renderem, inaczej interfejs mrugnie po polsku.
await initI18n()

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Brak elementu #root')
}

createRoot(rootElement).render(
  <StrictMode>
    <AppTheme>
      <CssBaseline />
      <DialogsProvider>
        <NotificationsProvider>
          <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </NotificationsProvider>
      </DialogsProvider>
    </AppTheme>
  </StrictMode>,
)
